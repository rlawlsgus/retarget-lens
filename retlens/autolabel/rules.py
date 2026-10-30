"""Rule files: which movement tracks (retlens.autolabel.segment) make which label.

RetLens holds no project's labels: a rule file names them and says when each applies, so a
project can keep its label definitions in its own file, outside this repository. YAML or JSON:

    name: 예시                          # optional, shown with the labels
    params: {gait: {max_pause: 0.5}}    # optional: thresholds of segment.DEFAULTS to change
    tracks:                             # one timeline lane each, in this order
      - track: 동작                     # the lane's name ("" or left out: a single unnamed lane)
        rules:                          # tried from the top for every frame; the first that holds labels it
          - {label: 걷기, when: {이동: [걷기, 계단 오르기, 계단 내리기]}}
          - {label: 손 뻗기, name: 팔을 내미는 중, when: [{왼손: 뻗기}, {오른손: 뻗기}]}
          - {label: 손 뻗기, when: {자세전환: 낮추기}, then: {손: [뻗기, 작업]}, within: 0.5}
          - {label: 정지}               # no when: every frame left (without it those stay unlabelled)
        min_seg: 0.3                    # optional: shorter pieces join their longer neighbour
      - {track: 이동, axis: 이동, skip: [정지]}   # a movement track shown as it is

when: {track: value or [values], ...} holds when every track listed has one of its values; a list
of those holds when any of them does. then + within (s): the rule holds on each stretch where
when holds and then holds somewhere from its start to within seconds after its end (a crouch that
ends in a reach). Rule keys besides: name (a longer name), color (#rrggbb): both belong to the
label, the first a rule of that label gives.
approach (per track, optional): {from: [labels], to: [labels], max_gap: s, steps: n, label: ..}
relabels the last n steps of a from-stretch that runs into a to-stretch (walking up to work).

A single lane may also be written with rules (and min_seg, approach) at the top instead of tracks.
Track names and values are checked against segment.VALUES, so a misspelt one is an error, not a
rule that never holds; so is a key written twice (the second would silently replace the first).
min_seg joins short labelled pieces to a labelled neighbour; frames no rule labels stay unlabelled.
"""

from __future__ import annotations

import json
import math
import os
import re

import numpy as np

from . import segment

RULE_KEYS = {"label", "name", "color", "when", "then", "within"}
TRACK_KEYS = {"track", "rules", "min_seg", "approach", "axis", "skip"}
MAX_NUMBER = 1e5  # s or steps: no time in a rule file is longer than a day (bigger ones overflow frame counts)
# YAML errors by kind, with no text of the file (PyYAML's own message quotes it)
YAML_KINDS = {"ScannerError": "들여쓰기·따옴표·특수 문자", "ParserError": "목록·표의 구조",
              "ComposerError": "목록·표의 구조", "ConstructorError": "쓸 수 없는 태그나 별칭"}


class RuleError(ValueError):
    pass


def _no_repeats(pairs):
    """A JSON object whose keys are all different."""
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise RuleError(f"읽지 못함: 같은 항목 '{k}'이(가) 한 표에 두 번 있습니다")
        seen[k] = v
    return seen


def _yaml_loader():
    """yaml.SafeLoader that refuses a key written twice in one mapping."""
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        seen = set()
        for k, _ in node.value:
            key = loader.construct_object(k, deep=deep)
            try:
                repeat = key in seen
                seen.add(key)
            except TypeError:  # a list or table as a key: SafeLoader says so
                continue
            if repeat:
                raise RuleError(f"읽지 못함: 같은 항목 '{key}'이(가) 한 표에 두 번 있습니다 ({k.start_mark.line + 1}행)")
        return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)

    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    return Loader


def load(path: str) -> dict:
    """A rule file, checked (RuleError says what is wrong and where). UTF-8 (with or without BOM) or
    CP949. A file that does not parse is reported by line and column only: its text may be a
    project's private label definitions, and the message goes to the window, logs and the API."""
    with open(path, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp949")
        except UnicodeDecodeError:
            raise RuleError("읽지 못함: UTF-8도 CP949도 아닌 글자가 있습니다") from None
    if os.path.splitext(path)[1].lower() == ".json":
        try:
            data = json.loads(text, object_pairs_hook=_no_repeats)
        except json.JSONDecodeError as e:
            raise RuleError(f"읽지 못함: JSON 형식 오류 ({e.lineno}행 {e.colno}열)") from None
    else:
        import yaml

        try:
            data = yaml.load(text, Loader=_yaml_loader())
        except yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            where = f" ({mark.line + 1}행 {mark.column + 1}열)" if mark is not None else ""
            raise RuleError(f"읽지 못함: YAML 형식 오류{where}: {YAML_KINDS.get(type(e).__name__, '형식이 맞지 않음')}") from None
    return check(data)


def _num(v, where: str, lo: float = 0.0, integer: bool = False) -> float:
    """A number the rules give (seconds, steps): finite, at least lo and at most MAX_NUMBER; RuleError otherwise."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= MAX_NUMBER or \
            (integer and v != int(v)):
        raise RuleError(f"{where}: {lo:g} 이상 {MAX_NUMBER:g} 이하의 {'정수' if integer else '숫자'}여야 합니다 (받은 값: {v!r})")
    return int(v) if integer else float(v)


def _names(v, where: str) -> list[str]:
    """A label or a list of them."""
    v = v if isinstance(v, list) else [v]
    if not v or not all(isinstance(x, (str, int, float)) and not isinstance(x, bool) and str(x).strip() for x in v):
        raise RuleError(f"{where}: 라벨 이름이나 그 목록이어야 합니다")
    return [str(x).strip() for x in v]


def check(data) -> dict:
    """The rules in their one form ({name, params, tracks: [...]}); RuleError on anything off, so
    applying them later cannot fail."""
    if not isinstance(data, dict):
        raise RuleError("규칙 파일의 맨 위는 name / params / tracks (또는 rules)를 가진 표여야 합니다")
    unknown = set(data) - {"name", "params", "tracks"} - TRACK_KEYS
    if unknown:
        raise RuleError(f"모르는 항목: {', '.join(sorted(map(str, unknown)))}")
    top = sorted(TRACK_KEYS & set(data))
    if "tracks" in data and top:  # they would belong to no lane and do nothing
        raise RuleError(f"tracks가 있으면 맨 위에 {', '.join(top)}를 쓸 수 없습니다 (레인 하나면 tracks 없이, 여럿이면 각 레인 안에)")
    tracks = data.get("tracks")
    if tracks is None:
        tracks = [{k: data[k] for k in TRACK_KEYS if k in data}]
    if not isinstance(tracks, list) or not tracks:
        raise RuleError("tracks는 레인 목록이어야 합니다")
    try:
        params = segment.params(data.get("params"))
    except ValueError as e:
        raise RuleError(str(e)) from e
    for group, vals in (data.get("params") or {}).items():
        for k, v in vals.items():
            if v > MAX_NUMBER:
                raise RuleError(f"params.{group}.{k}: {MAX_NUMBER:g} 이하여야 합니다 (받은 값: {v!r})")
    out = {"name": str(data.get("name") or ""), "params": params, "tracks": []}
    for i, t in enumerate(tracks):
        where = f"tracks[{i}]"
        if not isinstance(t, dict):
            raise RuleError(f"{where}: 표여야 합니다")
        bad = set(t) - TRACK_KEYS
        if bad:
            raise RuleError(f"{where}: 모르는 항목 {', '.join(sorted(map(str, bad)))}")
        name = t.get("track")
        if name is not None and (isinstance(name, (bool, list, dict))):
            raise RuleError(f"{where}: track(레인 이름)은 글자여야 합니다")
        name = str(name if name is not None else "").strip()
        where = f"레인 '{name}'" if name else where
        if "axis" in t:
            extra = {"rules", "min_seg", "approach"} & set(t)
            if extra:
                raise RuleError(f"{where}: axis 레인에는 {', '.join(sorted(extra))}를 쓸 수 없습니다 (규칙 레인을 따로 두세요)")
            axis = str(t["axis"])
            if axis not in segment.VALUES:
                raise RuleError(f"{where}: 모르는 트랙 '{axis}' (있는 것: {', '.join(segment.VALUES)})")
            skip = _values(axis, t.get("skip", []), where)
            out["tracks"].append({"track": name, "axis": axis, "skip": skip})
            continue
        if "skip" in t:
            raise RuleError(f"{where}: skip은 axis 레인에만 씁니다")
        rules = t.get("rules")
        if not isinstance(rules, list) or not rules:
            raise RuleError(f"{where}: rules(규칙 목록)나 axis(그대로 보일 트랙)가 있어야 합니다")
        checked = [_rule(r, f"{where} 규칙 {j + 1}") for j, r in enumerate(rules)]
        tr = {"track": name, "rules": checked, "min_seg": _num(t.get("min_seg", 0), f"{where} min_seg")}
        if t.get("approach"):
            tr["approach"] = _approach(t["approach"], {r["label"] for r in checked}, where)
        out["tracks"].append(tr)
    names = [t["track"] for t in out["tracks"]]
    if len(set(names)) != len(names):
        raise RuleError("레인 이름이 겹칩니다: " + ", ".join(names))
    return out


def _rule(r, where) -> dict:
    label = r.get("label") if isinstance(r, dict) else None
    if label is None or isinstance(label, (bool, list, dict)) or not str(label).strip():
        raise RuleError(f"{where}: label이 있어야 합니다")
    bad = set(r) - RULE_KEYS
    if bad:
        raise RuleError(f"{where}: 모르는 항목 {', '.join(sorted(map(str, bad)))} (쓸 수 있는 것: {', '.join(sorted(RULE_KEYS))})")
    out = {"label": str(r["label"]).strip(), "name": str(r.get("name") or ""), "color": r.get("color"),
           "when": _cond(r.get("when"), where + " when")}
    if "then" in r or "within" in r:
        if "then" not in r or "within" not in r or r.get("when") is None:
            raise RuleError(f"{where}: then과 within은 when과 함께 셋 다 있어야 합니다")
        out["then"] = _cond(r["then"], where + " then")
        out["within"] = _num(r["within"], f"{where} within")
    if out["color"] is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", str(out["color"])):
        raise RuleError(f"{where}: color는 #rrggbb여야 합니다")
    return out


def _cond(c, where) -> list[dict]:
    """when / then as [{track: [values]}] (any of the dicts, all tracks within one); [] = always."""
    if c is None or c == {} or c == []:
        return []
    alts = c if isinstance(c, list) else [c]
    out = []
    for a in alts:
        if not isinstance(a, dict) or not a:
            raise RuleError(f"{where}: {{트랙: 값}} 표나 그 목록이어야 합니다")
        d = {}
        for axis, vals in a.items():
            axis = str(axis)
            if axis not in segment.VALUES:
                raise RuleError(f"{where}: 모르는 트랙 '{axis}' (있는 것: {', '.join(segment.VALUES)})")
            d[axis] = _values(axis, vals, where)
        out.append(d)
    return out


def _values(axis, vals, where) -> list[str]:
    vals = [str(v) for v in (vals if isinstance(vals, list) else [vals])]
    for v in vals:
        ok = v in segment.VALUES[axis]
        if axis == "자세" and "→" in v:
            a, _, b = v.partition("→")
            ok = a in segment.POSTURE_RANK and b in segment.POSTURE_RANK and a != b  # A→A never happens
        if not ok:
            raise RuleError(f"{where}: {axis}에 '{v}' 값은 없습니다 (있는 것: {', '.join(segment.VALUES[axis])}"
                            + (", 그리고 'A→B' 꼴의 전환" if axis == "자세" else "") + ")")
    return vals


def _approach(a, labels, where) -> dict:
    need = {"from", "to", "label"}
    if not isinstance(a, dict) or not need <= set(a):
        raise RuleError(f"{where} approach: from, to, label이 있어야 합니다")
    bad = set(a) - need - {"max_gap", "steps"}
    if bad:
        raise RuleError(f"{where} approach: 모르는 항목 {', '.join(sorted(map(str, bad)))}")
    where += " approach"
    out = {"from": _names(a["from"], f"{where} from"), "to": _names(a["to"], f"{where} to"),
           "label": _names(a["label"], f"{where} label")[0],
           "max_gap": _num(a.get("max_gap", 0.5), f"{where} max_gap"),
           "steps": _num(a.get("steps", 2), f"{where} steps", lo=1, integer=True)}
    missing = [x for x in out["from"] + out["to"] if x not in labels]
    if missing:
        raise RuleError(f"{where}: 이 레인의 규칙에 없는 라벨 {', '.join(missing)}")
    return out


# ---------------------------------------------------------------- applying
def _holds(cond: list[dict], tr: dict, T: int) -> np.ndarray:
    if not cond:
        return np.ones(T, dtype=bool)
    m = np.zeros(T, dtype=bool)
    for alt in cond:
        a = np.ones(T, dtype=bool)
        for axis, vals in alt.items():
            a &= np.isin(tr[axis], vals)
        m |= a
    return m


def apply(rules: dict, tr: dict, steps: list) -> list[tuple[str, str, int, int, dict]]:
    """[(lane, label, start frame, end frame exclusive, {name, color})] at segment.FPS; frames no rule
    labels are left out. name and color belong to the label: the first given by any of its rules."""
    T = len(tr["이동"])
    out = []
    meta = {}  # per label, in every lane (axis lanes too): the first name and the first color any of its rules gives
    for t in rules["tracks"]:
        for r in t.get("rules", []):
            m_ = meta.setdefault(r["label"], {"name": "", "color": None})
            m_["name"] = m_["name"] or r["name"]
            m_["color"] = m_["color"] or r["color"]
    for t in rules["tracks"]:
        if "axis" in t:
            for lab, s, e in segment.labels_to_segments(tr[t["axis"]]):
                if lab not in t["skip"]:
                    out.append((t["track"], str(lab), s, e, meta.get(str(lab), {})))
            continue
        lab = np.full(T, None, dtype=object)
        done = np.zeros(T, dtype=bool)
        for r in t["rules"]:
            m = _holds(r["when"], tr, T)
            if "then" in r:  # within 0: then while when holds, not a frame after
                then, gap = _holds(r["then"], tr, T), int(round(r["within"] * segment.FPS))
                hit = np.zeros(T, dtype=bool)
                for a, b in segment.runs(m):
                    if then[a:min(T, b + gap)].any():
                        hit[a:b] = True
                m = hit
            m &= ~done
            lab[m] = r["label"]
            done |= m
        if t["min_seg"]:
            lab = _smooth_labelled(lab, t["min_seg"])
        if t.get("approach"):
            _approach_steps(lab, t["approach"], steps)
            meta.setdefault(t["approach"]["label"], {"name": "", "color": None})
        for name, s, e in segment.labels_to_segments(lab):
            if name is not None:
                out.append((t["track"], name, s, e, meta[name]))
    return out


def _smooth_labelled(lab, min_seg: float):
    """min_seg within each stretch of labelled frames: a short piece joins its longer labelled
    neighbour. Unlabelled frames are not a label: they take no piece over and are not filled."""
    lab = lab.copy()
    for a, b in segment.runs(np.array([x is not None for x in lab], dtype=bool)):
        lab[a:b] = segment.smooth_labels(lab[a:b], min_seg)
    return lab


def _approach_steps(lab, ap, steps) -> None:
    segs = segment.labels_to_segments(lab)
    gap = int(round(ap["max_gap"] * segment.FPS))
    lifts = np.array([x["lift"] for x in steps], dtype=int)
    for i, (name, s, e) in enumerate(segs):
        if name not in ap["from"]:
            continue
        j = i + 1
        while j < len(segs) and segs[j][2] - segs[j][1] <= gap and segs[j][0] not in ap["to"]:
            j += 1
        if j < len(segs) and segs[j][0] in ap["to"] and segs[j][1] - e <= gap:
            inside = lifts[(lifts >= s) & (lifts < e)]
            if len(inside) >= ap["steps"]:
                lab[inside[-ap["steps"]]:e] = ap["label"]
