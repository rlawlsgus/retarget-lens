"""Body joints and body sizes for the movement tracks, from the human motions RetLens opens.

The tracks need 17 joints (signals.JOINTS) at 30 fps and six body sizes (signals.DIMS):
- AMASS SMPL / SMPL-X: the joints by name, the sizes from the body model and the motion's
  betas, measured on the rest pose (stature and the sole from the mesh).
- BVH / FBX: the joints matched by name the way retargeting matches them (retlens.retarget),
  the sizes estimated from the bone lengths with body proportions of Winter (2009),
  Biomechanics and Motor Control of Human Movement, table 4.1: thigh 0.245 H and shank 0.246 H
  of stature H, ankle height 0.039 H; the toe joint's height from how far it sits below the
  ankle while the foot stands flat.
"""

from __future__ import annotations

import numpy as np

from ..motion import SkeletonMotion
from .signals import FPS, JOINTS, resample, support_velocity

LEG = 0.245 + 0.246  # thigh + shank / stature
ANKLE = 0.039  # ankle height / stature
_SMPL = {"pelvis": "pelvis", "head": "head", "spine3": "spine3",
         **{f"{s}_{j}": f"{side}_{j}" for s, side in (("l", "left"), ("r", "right"))
            for j in ("hip", "knee", "ankle", "foot", "shoulder", "elbow", "wrist")}}
_TOES = ("LeftToeBase", "LeftToe", "LeftToes", "LToe", "lToe", "left_foot", "left_toe")
_HEADS = ("Head", "head", "HEAD")


def joint_index(human: SkeletonMotion) -> dict[str, int]:
    """signals.JOINTS -> the motion's joint index. ValueError naming what is missing."""
    names = list(human.joint_names)
    lookup = {n: i for i, n in enumerate(names)}
    if all(v in lookup for v in _SMPL.values()):
        return {k: lookup[v] for k, v in _SMPL.items()}
    from ..retarget import _HIPS_ALIASES, _LEFT_ALIASES, _right_alias, _strip_common_prefix

    names = _strip_common_prefix(names)
    lookup = {n: i for i, n in enumerate(names)}
    parents = np.asarray(human.parents)

    def find(aliases, side, what):
        cands = list(aliases) if side == "l" else [_right_alias(a) for a in aliases]
        j = next((lookup[c] for c in cands if c in lookup), None)
        if j is None:
            raise ValueError(f"{'왼' if side == 'l' else '오른'}쪽 {what} 관절이 없습니다 (찾아본 이름: {', '.join(cands)})")
        return j

    idx = {"pelvis": next((lookup[a] for a in _HIPS_ALIASES if a in lookup),
                          next(i for i, p in enumerate(parents) if p < 0))}
    for s in ("l", "r"):
        for ours, part, what in (("hip", "UpLeg", "엉덩"), ("knee", "Leg", "무릎"), ("ankle", "Foot", "발목"),
                                 ("shoulder", "Arm", "어깨"), ("elbow", "ForeArm", "팔꿈치"), ("wrist", "Hand", "손목")):
            idx[f"{s}_{ours}"] = find(_LEFT_ALIASES[part], s, what)
        try:
            idx[f"{s}_foot"] = find(_TOES, s, "발끝")
        except ValueError:  # no toe joint by name: the ankle's child (a toe end site at least)
            kids = [i for i, p in enumerate(parents) if p == idx[f"{s}_ankle"]]
            if not kids:
                raise
            idx[f"{s}_foot"] = kids[0]
    # chest = the spine joint the arm hangs from (past a clavicle / shoulder joint), as retargeting takes it
    p = int(parents[idx["l_shoulder"]])
    if any(k in names[p].lower() for k in ("shoulder", "clavicle", "collar")):
        p = int(parents[p])
    idx["spine3"] = p
    head = next((lookup[h] for h in _HEADS if h in lookup), None)
    if head is None:
        raise ValueError("머리 관절(Head)이 없습니다")
    idx["head"] = head
    return idx


def dims_from_model(model_path: str, betas, num_betas: int = 16) -> dict:
    """Body sizes of an SMPL-family body model with these betas, on its rest pose (model Y up)."""
    m = np.load(model_path, allow_pickle=True)
    b = np.zeros(num_betas)
    betas = np.asarray(betas, dtype=np.float64).reshape(-1)
    b[:min(len(betas), num_betas)] = betas[:num_betas]
    v = m["v_template"].astype(np.float64) + m["shapedirs"][:, :, :num_betas].astype(np.float64) @ b
    reg = m["J_regressor"]
    if reg.dtype == object:  # scipy sparse pickled into the npz
        reg = reg.item().toarray()
    j = np.asarray(reg, dtype=np.float64)[:22] @ v
    sole = v[:, 1].min()
    dist = lambda a, c: float(np.linalg.norm(j[a] - j[c]))
    # SMPL joint order: 0 pelvis, 1 left_hip, 4 left_knee, 7 left_ankle, 10 left_foot, 16 / 18 / 20 left shoulder / elbow / wrist
    return {"stature": float(v[:, 1].max() - sole), "arm": dist(16, 18) + dist(18, 20), "pelvis_h": float(j[0, 1] - sole),
            "h_ankle": float(j[7, 1] - sole), "h_toe": float(j[10, 1] - sole), "thigh": dist(1, 4)}


def dims_from_motion(P: dict) -> tuple[dict, list[str]]:
    """Body sizes estimated from the bone lengths of a skeleton (30 fps joints), and how."""
    bone = lambda a, b: float(np.median(np.linalg.norm(P[a] - P[b], axis=1)))
    thigh = (bone("l_hip", "l_knee") + bone("r_hip", "r_knee")) / 2
    shank = (bone("l_knee", "l_ankle") + bone("r_knee", "r_ankle")) / 2
    stature = (thigh + shank) / LEG
    h_ankle = ANKLE * stature
    notes = ["체형(키·발목 높이 등)은 몸 모델이 없어 뼈 길이로 추정함 (BVH·FBX). 같은 촬영의 SMPL-X와는 "
             "관절 위치가 달라 라벨이 조금 다를 수 있음"]
    # the toe joint sits below the ankle joint by (h_ankle - h_toe) while the foot stands flat and still;
    # on a treadmill the standing foot goes with the belt, so still is looked for in the belt's frame
    belt = support_velocity(P, {"h_ankle": h_ankle, "h_toe": h_ankle / 2})
    t = np.arange(len(P["pelvis"]))[:, None] / FPS
    shift = np.concatenate([belt[None, :] * t, np.zeros_like(t)], axis=1)
    drops = []
    for s in ("l", "r"):
        ank, toe = P[f"{s}_ankle"] - shift, P[f"{s}_foot"] - shift
        still = (np.linalg.norm(np.gradient(ank, 1 / FPS, axis=0), axis=1) < 0.1) & \
                (np.linalg.norm(np.gradient(toe, 1 / FPS, axis=0), axis=1) < 0.1)
        drops.append((ank[:, 2] - toe[:, 2])[still])
    drop = np.concatenate(drops)
    if len(drop) >= 10:
        h_toe = float(np.clip(h_ankle - np.median(drop), 0.005, h_ankle))
    else:
        h_toe = h_ankle / 2
        notes.append("발이 바닥에 멈춰 있는 순간이 없어 발끝 관절 높이를 발목 높이의 절반으로 둠")
    pel = P["pelvis"]
    above_hips = float(np.median(np.linalg.norm(pel - (P["l_hip"] + P["r_hip"]) / 2, axis=1)))
    arm = (bone("l_shoulder", "l_elbow") + bone("l_elbow", "l_wrist") +
           bone("r_shoulder", "r_elbow") + bone("r_elbow", "r_wrist")) / 2
    return {"stature": stature, "arm": arm, "pelvis_h": h_ankle + shank + thigh + above_hips, "h_ankle": h_ankle,
            "h_toe": h_toe, "thigh": thigh}, notes


def prepare(human: SkeletonMotion) -> tuple[dict, dict, list[str]]:
    """({joint: (T, 3)} at 30 fps, body sizes, notes) for segment.tracks."""
    if human.kind != "skeleton":
        raise ValueError("마커만 있는 모션입니다. 같은 촬영의 골격(BVH·FBX·AMASS)이 필요합니다")
    idx = joint_index(human)
    pos = np.asarray(human.positions, dtype=np.float64)[:, [idx[k] for k in JOINTS]]
    if not np.isfinite(pos).all():
        raise ValueError("관절 위치에 빈 값(NaN)이 있습니다")
    if not human.fps > 0:
        raise ValueError(f"모션의 fps가 {human.fps}입니다")
    P30 = resample(pos, human.fps, FPS)
    if len(P30) < 2:
        raise ValueError(f"너무 짧습니다: {human.num_frames}프레임 ({human.duration:.3f} s). "
                         f"자동 라벨은 {FPS:g} fps로 2프레임({2 / FPS:.2f} s) 이상이어야 합니다")
    P = {k: P30[:, i] for i, k in enumerate(JOINTS)}
    model = human.meta.get("model_path")
    if model and human.meta.get("betas") is not None:
        dims = dims_from_model(model, human.meta["betas"])
        return P, dims, [f"체형은 몸 모델과 betas로 계산: 키 {dims['stature']:.2f} m"]
    dims, notes = dims_from_motion(P)
    return P, dims, notes
