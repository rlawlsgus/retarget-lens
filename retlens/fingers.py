"""Fingers: a robot hand with jointed fingers follows the person's fingers, after the body's IK.

The IK (GMR) places the hands; it has no finger targets, so a robot's finger joints stayed at 0 (straight).
retarget_fingers sets them from the human skeleton's finger chains:

- the human's fingers (human_fingers): below each hand joint, one chain per child down to its end (end site
  included), named by its joints: thumb / index / middle / ring / pinky (Biped Finger0..4, Mixamo LeftHandIndex1,
  SMPL-X left_index1, ...); with no thumb by name the chain whose base is nearest the hand is the thumb, and other
  unnamed chains take the fingers not taken, nearest the thumb first;
- how much each joint bends (finger_bends), from joint positions only (the human's and the robot's joint axes need
  not agree), in the palm's frame (HandFrame: long axis hand -> finger bases, across axis along them, normal towards
  the palm, the side the fingers' middle joints bend to): a finger's first joint by the turn of its first segment
  towards the palm (spread left out); the thumb's first joint by how far its first segment rises out of the palm
  plane towards the palm; the other joints by the angle between the segments meeting at them. Each minus its
  straight value, never below 0: the rest pose's (FBX / BVH rest) where the rest is nearly straight; where it is
  curled (Biped binds its fingers relaxed) or there is none, the clip's 5th percentile capped at 15 deg. A first
  joint on the hand joint's own place (CMU BVH) is not measured;
- per robot finger (retlens.robot_profile._fingers) the human finger of its kind (a missing ring / pinky: the
  nearest one present), its bends spread over the robot finger's closing joints by joint count (3 human joints on
  2 robot joints: the first gets the first and half the second, the other the rest; segment lengths are not
  weighed), times the joint's closing sign, clipped to the joint's range. Joints that do not close the hand (a
  thumb's twist, a spread) keep their value. Then the usual smoothing follows (retarget_file).

Timing: robot frame i takes the human pose at i / fps, as the viewers pair them (retlens.retarget_quality).
"""

from __future__ import annotations

import re

import numpy as np

from .motion import RobotMotion, SkeletonMotion
from .robot_profile import FINGER_KINDS, SIDES

VERSION = 4  # bump when retarget_fingers' results change (retarget caches of robots with fingers; 4: rest per joint)
HUMAN_SIDE = {"left": "Left", "right": "Right"}
# a chain's own (first) joint name first, then any of its joints; "finger1" not followed by a digit (Biped Finger12
# is the index's last joint, Finger032_End the ring's end)
HUMAN_WORDS = {"thumb": r"thumb|pollex|finger0(?!\d)", "index": r"index|pointer|finger1(?!\d)",
               "middle": r"middle|finger2(?!\d)", "ring": r"ring|finger3(?!\d)", "pinky": r"pinky|little|finger4(?!\d)"}
NEAREST = {"thumb": (), "index": ("middle",), "middle": ("index", "ring"), "ring": ("middle", "pinky"),
           "pinky": ("ring", "middle"), "finger": ("index", "middle")}
REST_PERCENTILE = 5
REST_STRAIGHT_DEG = 15.0  # a rest-pose joint bent less than this is the skeleton's straight; more: a relaxed hand
SAME_PLACE_M = 0.005  # joints this close sit on one place (CMU's LeftFingerBase on LeftHand)
PALM_DOWN_COS = 0.5  # a rest palm normal this close to vertical says which side is the palm (it faces down)
VOTE_MIN_DEG = 10.0  # middle-joint bends past rest by more than this tell the palm side from the clip
# fingers numbered from 1 with the thumb first (a chain named ...finger5 exists): LeftFinger1 = thumb
HUMAN_WORDS_1 = {"thumb": r"thumb|pollex|finger1(?!\d)", "index": r"index|pointer|finger2(?!\d)",
                 "middle": r"middle|finger3(?!\d)", "ring": r"ring|finger4(?!\d)", "pinky": r"pinky|little|finger5(?!\d)"}


def _kind(names: list[str], words: dict | None = None) -> str | None:
    for text in (names[0], " ".join(names)):
        for kind, rx in (words or HUMAN_WORDS).items():
            if re.search(rx, text):
                return kind
    return None


def human_fingers(h: SkeletonMotion) -> dict[str, dict]:
    """{side: {"hand": joint index, "fingers": {kind: [joint indices, base -> end]}}} of a skeleton; a side without
    finger chains has none. Kinds by name; no thumb by name: the chain whose base is nearest the hand; other unnamed
    chains take the fingers left, nearest the thumb's base first. ValueError when the hands cannot be found."""
    from .retarget import _resolve_bvh_bodies, _strip_common_prefix

    idx = _resolve_bvh_bodies(h.joint_names, h.parents)
    names = [n.lower() for n in _strip_common_prefix(list(h.joint_names))]
    parents = np.asarray(h.parents)
    kids = {i: [] for i in range(len(names))}
    for i, p in enumerate(parents):
        if p >= 0:
            kids[int(p)].append(i)
    rest, _ = rest_positions(h)
    P0 = rest if rest is not None else h.positions[0]

    def size(i):
        n, stack = 0, [i]
        while stack:
            x = stack.pop()
            n += 1
            stack.extend(kids[x])
        return n

    out = {}
    for side in SIDES:
        hand = idx[f"{HUMAN_SIDE[side]}Hand"]
        chains = []
        for c in kids[hand]:
            chain, b = [c], c
            while kids[b]:
                b = max(kids[b], key=size)
                chain.append(b)
            if len(chain) >= 2:  # a lone end site or nub is not a finger
                chains.append(chain)
        # Biped numbers the fingers from 0 (Finger0 = thumb); a skeleton with a fifth "finger5" numbers them from 1
        words = HUMAN_WORDS_1 if any(re.search(r"finger5(?!\d)", names[ch[0]]) for ch in chains) else HUMAN_WORDS
        named, unnamed = {}, []
        for chain in chains:
            kind = _kind([names[k] for k in chain], words)
            if kind and kind not in named:
                named[kind] = chain
            else:
                unnamed.append(chain)

        def dist(a, b):
            return float(np.linalg.norm(P0[a] - P0[b]))

        if "thumb" not in named and unnamed and len(chains) >= 2:  # the unnamed chain nearest the hand, when it is
            # nearer than every named one
            thumb = min(unnamed, key=lambda ch: dist(ch[0], hand))
            if all(dist(thumb[0], hand) < dist(ch[0], hand) for ch in named.values()):
                named["thumb"] = thumb
                unnamed.remove(thumb)
        if "thumb" in named:
            unnamed.sort(key=lambda ch: dist(ch[0], named["thumb"][0]))
        free = [k for k in FINGER_KINDS if k not in named and k != "thumb"]
        for chain in unnamed:
            if free:
                named[free.pop(0)] = chain
        if named:
            out[side] = {"hand": int(hand), "fingers": named}
    return out


def _angles(P: np.ndarray, points: list[int]) -> np.ndarray:
    """(T, n) angles (rad) at the inner points of a polyline through `points`, over frames P (T, J, 3)."""
    seg = P[:, points[1:]] - P[:, points[:-1]]
    a, b = seg[:, :-1], seg[:, 1:]
    na, nb = np.linalg.norm(a, axis=-1), np.linalg.norm(b, axis=-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        c = np.einsum("...i,...i->...", a, b) / (na * nb)
    return np.arccos(np.clip(np.nan_to_num(c, nan=1.0), -1.0, 1.0))


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(n > 1e-9, n, 1.0)


def rest_positions(h: SkeletonMotion) -> tuple[np.ndarray | None, str]:
    """(J, 3) rest-pose joint positions of a skeleton and where they came from; None when it has none."""
    rest = h.meta.get("rest_pose")
    if rest is not None:
        P = np.asarray(rest[0], dtype=float)
        if P.shape == (len(h.joint_names), 3):
            return P, "rest pose"
    if h.source.lower().endswith(".bvh"):
        try:
            from .io.bvh import bvh_rest_pose

            names, P, _ = bvh_rest_pose(h.source, scale=h.meta.get("unit_scale", "auto"))
            if list(names) == list(h.joint_names):
                return P, "rest pose"
        except Exception:
            pass
    return None, "clip"


class HandFrame:
    """The palm's frame of one human hand over frames (T, 3) and at rest (1, 3): long axis hand -> the non-thumb
    fingers' bases, across axis along those bases (to the thumb's base when there is one other finger), normal
    towards the palm. The palm side: down at rest when the rest pose's palm faces clearly down or up (T-pose
    skeletons rest palms down); else where the fingers' middle joints bend to over the clip (bends more than
    VOTE_MIN_DEG past their rest bend only); else the thumb's side."""

    def __init__(self, P: np.ndarray, R: np.ndarray, hand: int, fingers: dict):
        others = [fingers[k] for k in FINGER_KINDS[1:] if k in fingers]
        thumb = fingers.get("thumb")
        self.ok = bool(others) and (len(others) >= 2 or thumb is not None)
        if not self.ok:
            return
        # a palm with no size (the finger bases on the hand joint, or on one point): no frame to measure in
        B0 = R[0, [ch[0] for ch in others]]
        spread0 = (B0[-1] - B0[0]) if len(others) >= 2 else (R[0, thumb[0]] - B0[0])
        if float(np.linalg.norm(B0.mean(0) - R[0, hand])) < SAME_PLACE_M or float(np.linalg.norm(spread0)) < SAME_PLACE_M:
            self.ok = False
            return
        self.frames = {}
        for key, X in (("t", P), ("r", R)):
            B = X[:, [ch[0] for ch in others]]
            centre = B.mean(1)
            e1 = _unit(centre - X[:, hand])
            a = (B[:, -1] - B[:, 0]) if len(others) >= 2 else (X[:, thumb[0]] - B[:, 0])
            a = _unit(a - np.einsum("ti,ti->t", a, e1)[:, None] * e1)
            self.frames[key] = (X[:, hand], centre, e1, a, np.cross(e1, a))
        # the palm side: down at rest when the rest pose has the palms clearly down or up (T-pose skeletons rest palms
        # down); else where the fingers' middle joints bend to over the clip (counting only bends well past their rest
        # bend); else the thumb's side
        _, centre_r, _, _, n_r = self.frames["r"]
        vote = -float(n_r[0, 2]) if abs(float(n_r[0, 2])) > PALM_DOWN_COS else 0.0
        if vote == 0.0:
            _, _, _, _, n = self.frames["t"]
            for ch in others:
                if len(ch) >= 3:
                    u1, u2 = _unit(P[:, ch[1]] - P[:, ch[0]]), _unit(P[:, ch[2]] - P[:, ch[1]])
                    bend = np.arccos(np.clip(np.einsum("ti,ti->t", u1, u2), -1, 1))
                    r1, r2 = _unit(R[:, ch[1]] - R[:, ch[0]]), _unit(R[:, ch[2]] - R[:, ch[1]])
                    extra = bend - float(np.arccos(np.clip(np.einsum("ti,ti->t", r1, r2), -1, 1))[0])
                    big = extra > np.radians(VOTE_MIN_DEG)
                    vote += float(np.sum(extra[big] * np.einsum("ti,ti->t", u2 - u1, n)[big]))
        if vote == 0.0 and thumb is not None:
            vote = float((R[0, thumb[-1]] - centre_r[0]) @ n_r[0])
        self.side = 1.0 if vote >= 0 else -1.0

    def flex(self, X: np.ndarray, key: str, a: int, b: int) -> np.ndarray:
        """(T,) the angle (rad) of segment a -> b from the long axis towards the palm, spread left out."""
        _, _, e1, _, n = self.frames[key]
        v = X[:, b] - X[:, a]
        return np.arctan2(self.side * np.einsum("ti,ti->t", v, n), np.einsum("ti,ti->t", v, e1))

    def rise(self, X: np.ndarray, key: str, a: int, b: int) -> np.ndarray:
        """(T,) the angle (rad) of segment a -> b out of the palm plane towards the palm (a thumb closing over it)."""
        _, _, _, _, n = self.frames[key]
        v = X[:, b] - X[:, a]
        up = np.einsum("ti,ti->t", v, n)
        return np.arctan2(self.side * up, np.linalg.norm(v - up[:, None] * n, axis=-1))


def _zero(rest_val, clip_vals: np.ndarray) -> tuple[float, str]:
    """The value that counts as a straight joint and where it came from ("rest" / "clip"): the rest pose's when it
    is nearly straight there (below REST_STRAIGHT_DEG: a skeleton whose bones are not quite in line); a rest pose
    curled there (3ds Max Biped binds its fingers relaxed) or none: the clip's REST_PERCENTILE value (its most open),
    at most REST_STRAIGHT_DEG, so a hand relaxed all clip long stays curled on the robot."""
    cap = np.radians(REST_STRAIGHT_DEG)
    if rest_val is not None and np.isfinite(rest_val) and rest_val < cap:
        return float(rest_val), "rest"
    p = float(np.nanpercentile(clip_vals, REST_PERCENTILE)) if np.isfinite(clip_vals).any() else 0.0
    return min(p, cap), "clip"


def finger_bends(h: SkeletonMotion, hand: dict, frames: np.ndarray, rest: np.ndarray | None,
                 used: dict | None = None) -> dict[str, np.ndarray]:
    """{kind: (T, n) how far each joint of a finger bends (rad) at the given (fractional) human frames}. The first
    joint: for a finger, its first segment's turn towards the palm in the palm's frame (spread left out); for the
    thumb, how far its first segment rises out of the palm plane towards the palm. The others: the angle between the
    segments meeting at them. Each minus its straight value (_zero), at least 0. A first joint at the hand joint's
    own place (CMU's LeftFingerBase / LThumb) has no segment to measure from: it is left out (n one less).
    ``used`` {"rest": n, "clip": m} counts where the joints' straight values came from (added to)."""
    fingers = hand["fingers"]
    pts = sorted({hand["hand"], *[j for ch in fingers.values() for j in ch]})
    i0 = np.floor(frames).astype(int)
    i1 = np.minimum(i0 + 1, h.num_frames - 1)
    w = (frames - i0)[:, None, None]
    P = np.zeros((len(frames), len(h.joint_names), 3))
    P[:, pts] = (1 - w) * h.positions[i0][:, pts] + w * h.positions[i1][:, pts]
    every = h.positions  # all frames: the clip's most open values
    R = rest[None] if rest is not None else every[:1]
    frame_t = HandFrame(P, R, hand["hand"], fingers)
    frame_all = HandFrame(every, R, hand["hand"], fingers)
    out = {}
    for kind, ch in fingers.items():
        cols = []
        for k in range(len(ch) - 1):  # joint k bends between segment k-1 (or the palm) and segment k
            if k == 0 and float(np.linalg.norm(R[0, ch[0]] - R[0, hand["hand"]])) < SAME_PLACE_M:
                continue  # the finger's base sits on the hand joint: nothing to measure its first joint from
            if k == 0 and frame_t.ok:
                f = frame_t.rise if kind == "thumb" else frame_t.flex
                g = frame_all.rise if kind == "thumb" else frame_all.flex
                now = f(P, "t", ch[0], ch[1])
                ref, src = _zero(f(R, "r", ch[0], ch[1])[0] if rest is not None else None, g(every, "t", ch[0], ch[1]))
            else:  # the angle at ch[k] between the segments meeting there (the first: from the hand joint)
                poly = [hand["hand"], ch[0], ch[1]] if k == 0 else list(ch[k - 1:k + 2])
                now = _angles(P, poly)[:, 0]
                ref, src = _zero(_angles(R, poly)[0, 0] if rest is not None else None, _angles(every, poly)[:, 0])
            if used is not None:
                used[src] = used.get(src, 0) + 1
            cols.append(now - ref)
        out[kind] = np.clip(np.stack(cols, 1), 0.0, None) if cols else np.zeros((len(frames), 0))
    return out


def spread(values: np.ndarray, m: int) -> np.ndarray:
    """(T, n) bends of n human joints over m robot joints by joint count: with each joint an equal share of the
    finger, robot joint k takes the part of each human joint that falls in its share (sums are kept)."""
    T, n = values.shape
    if m <= 0 or n == 0:
        return np.zeros((T, max(m, 0)))
    W = np.zeros((m, n))
    for k in range(m):
        a, b = k / m, (k + 1) / m
        for i in range(n):
            lo, hi = max(a, i / n), min(b, (i + 1) / n)
            if hi > lo:
                W[k, i] = (hi - lo) * n
    return values @ W.T


def retarget_fingers(m: RobotMotion, h: SkeletonMotion, prof) -> tuple[RobotMotion, dict | None]:
    """The robot motion with its finger joints following the human's fingers (module notes), and what was done:
    {"version", "rest", "rest_joints", "fingers": {side: {robot finger: {"from": human finger, "joints": [...],
    "max_deg": [...]}}}, "notes"}. "rest": what the bends count from, "rest pose" (every human finger joint straight
    in it), "clip" (none, or no rest pose: the clip's most open) or "mixed"; "rest_joints" {"rest": n, "clip": m}
    how many joints of both hands took which. None when the robot has no jointed fingers."""
    parts = prof.parts
    if not any(parts.fingers.values()):
        return m, None
    notes = []
    try:
        hands = human_fingers(h)
    except ValueError as e:
        return m, {"version": VERSION, "fingers": {}, "notes": [f"사람 손을 찾지 못함: {e}"]}
    if not hands:
        return m, {"version": VERSION, "fingers": {}, "notes": ["사람 골격에 손가락 관절이 없음: 로봇 손가락은 펴진 채"]}
    rest, rest_from = rest_positions(h)
    frames = np.clip(np.arange(m.num_frames) / m.fps * h.fps, 0, h.num_frames - 1)
    used = {"rest": 0, "clip": 0}  # where each human finger joint's straight value came from (_zero)
    bends = {side: finger_bends(h, hs, frames, rest, used) for side, hs in hands.items()}
    if used["rest"] or used["clip"]:  # the rest pose only where it is straight (a Biped's relaxed hand: the clip)
        rest_from = "mixed" if used["rest"] and used["clip"] else "rest pose" if used["rest"] else "clip"
    model = prof.model()
    col = {n: i for i, n in enumerate(m.joint_names)}
    dof = m.dof_pos.copy()
    done: dict = {}
    for side in SIDES:
        hs = hands.get(side)
        if not parts.fingers.get(side):
            continue
        if hs is None:
            notes.append(f"{side}: 사람 손가락 없음")
            continue
        for f in parts.fingers[side]:
            src = f.kind if f.kind in hs["fingers"] else next((k for k in NEAREST.get(f.kind, ()) if k in hs["fingers"]),
                                                              None)
            if src is None:
                notes.append(f"{side} {f.kind}: 맞는 사람 손가락 없음")
                continue
            bend = bends[side][src]
            if bend.shape[1] == 0:
                notes.append(f"{side} {src}: 사람 손가락 마디를 잴 수 없음(뿌리가 손 관절과 같은 자리)")
            closing = [(j, c) for j, c in zip(f.joints, f.close) if c]
            if not closing:
                notes.append(f"{side} {f.kind}: 손을 오므리는 관절을 찾지 못함")
            vals = spread(bend, len(closing))
            names, peaks = [], []
            for k, (j, c) in enumerate(closing):
                name = prof.joint(j)
                if name not in col:
                    continue
                lo, hi = model.jnt_range[j] if model.jnt_limited[j] else (-np.pi, np.pi)
                dof[:, col[name]] = np.clip(c * vals[:, k], lo, hi)
                names.append(name)
                peaks.append(round(float(np.degrees(np.abs(dof[:, col[name]]).max())), 1))
            key = f.kind if f.kind not in done.get(side, {}) else f"{f.kind}{len(done[side]) + 1}"  # several "finger"s
            done.setdefault(side, {})[key] = {"from": src, "joints": names, "max_deg": peaks}
    out = RobotMotion(name=m.name, joint_names=list(m.joint_names), root_pos=m.root_pos, root_quat=m.root_quat,
                      dof_pos=dof, fps=m.fps, source=m.source, meta=dict(m.meta))
    return out, {"version": VERSION, "rest": rest_from, "rest_joints": used, "fingers": done, "notes": notes}
