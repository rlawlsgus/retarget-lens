"""Download a few small public mocap clips into data/raw/ for end-to-end checks.

    python tools/fetch_samples.py                 # all sets
    python tools/fetch_samples.py cmu unitree     # pick sets

Every file is pinned to a repository revision and checked against the hash the
host publishes for it (git blob SHA-1, or the Git LFS SHA-256). Each set gets a
SOURCE.md with the origin, revision and licence, because the licences differ:

  cmu      CMU Graphics Lab mocap, cgspeed 2010 BVH conversion (2.3 MB).
           Free for research and commercial use, redistribution allowed;
           do not sell the data itself. -> redistributable (RetLens samples).
  cmu_fbx  The same six CMU clips as FBX (Hugging Face gbionics/cmu-fbx, 0.8 MB):
           RancidMilk's Blender conversion of the cgspeed Daz-friendly BVHs.
           CMU terms -> redistributable.
  unitree  Unitree's G1 retarget of LAFAN1 (csv, 30 fps, 8 MB).
           CC BY-NC-ND 4.0 -> internal validation only, never redistribute.
  lafan1   Ubisoft LAFAN1 BVH for the same four clips (137 MB zip; only the
           four BVHs are kept). CC BY-NC-ND 4.0 -> internal validation only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import tempfile
import urllib.request
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
RAW = os.path.join(ROOT, "data", "raw")

LAFAN_CLIPS = ["walk1_subject1", "run1_subject2", "dance1_subject1", "fallAndGetUp1_subject1"]

SETS = {
    "cmu": {
        "folder": "cmu_bvh",
        "host": "github",
        "repo": "una-dinosauria/cmu-mocap",
        "rev": "09a07f54f3bbb58797325f009282d0b2048a2871",
        "files": {
            "data/002/02_01.bvh": "02_01.bvh",    # walk
            "data/002/02_03.bvh": "02_03.bvh",    # run/jog
            "data/016/16_17.bvh": "16_17.bvh",    # walk, 90-degree left turn
            "data/143/143_11.bvh": "143_11.bvh",  # walk and pick up box
            "data/143/143_13.bvh": "143_13.bvh",  # walk and pick up laundry basket
            "data/143/143_28.bvh": "143_28.bvh",  # sweeping, push broom
            "READMEFIRST.txt": "READMEFIRST.txt",  # conversion notes + usage rights
        },
        "license": "CMU Graphics Lab Motion Capture Database terms + cgspeed conversion (no added restrictions)",
        "usage": "재배포 가능. 상업 사용·재배포 허용, 데이터 자체 판매만 금지. "
                 "논문 사사: \"The data used in this project was obtained from mocap.cs.cmu.edu. "
                 "The database was created with funding from NSF EIA-0196217.\"",
        "notes": "cgspeed 변환본은 모든 파일의 0번 프레임에 T-pose를 끼워 넣었다(원본 캡처 아님). "
                 "파일에는 모두 120 fps로 적혀 있지만 143번 등 일부 피험자는 60 Hz 촬영이다(BVH 로더가 "
                 "retlens/io/cmu_frame_rates.json으로 보정). Y-up, 단위 inch/0.45. 손가락·엄지 관절은 데이터 없음.",
    },
    "cmu_fbx": {
        "folder": "cmu_fbx",
        "host": "hf",
        "repo": "gbionics/cmu-fbx",
        "rev": None,
        "files": {**{f"animations/{c}.fbx": f"{c}.fbx" for c in ("02_01", "02_03", "16_17", "143_11", "143_13", "143_28")},
                  "README.md": "README.md", "metadata.csv": "metadata.csv"},
        "license": "CMU Graphics Lab Motion Capture Database terms (데이터셋 카드: license other / cmu-mocap)",
        "usage": "재배포 가능(CMU 약관). 데이터 자체 판매 금지, 재배포 시 같은 조건과 mocap.cs.cmu.edu 사사 표기.",
        "notes": "RancidMilk가 cgspeed의 Daz판 BVH를 Blender + Auto-Rig Pro로 게임 캐릭터(Quaternius CC0) 골격에 옮겨 "
                 "FBX로 내보낸 것(뼈대만, 손가락 없음). 관절 이름 hip/abdomen/lThigh…(Daz), 30 fps로 다시 뽑음. "
                 "0번 프레임은 T-pose. cgspeed의 120 Hz 가정을 물려받아 60 Hz 피험자(143)는 2배속 -> load_fbx가 보정. "
                 "수치는 cm인데 장면 단위가 m라 100배 큼 -> load_fbx가 자동 보정.",
    },
    "unitree": {
        "folder": "unitree_lafan1_g1",
        "host": "hf",
        "repo": "lvhaidong/LAFAN1_Retargeting_Dataset",
        "rev": None,  # resolved to the current commit and recorded in SOURCE.md
        "files": {**{f"g1/{c}.csv": f"{c}.csv" for c in LAFAN_CLIPS}, "LICENSE": "LICENSE", "README.md": "README.md"},
        "license": "CC BY-NC-ND 4.0 (LAFAN1 원천 데이터 라이선스를 따름)",
        "usage": "내부 검증 전용. 재배포·파생물 공유 금지(리타겟 결과 포함).",
        "notes": "헤더 없는 csv: root xyz, root quat xyzw, G1 29관절(MJCF 순서). 30 fps.",
    },
    "lafan1": {
        "folder": "lafan1_bvh",
        "host": "github_lfs_zip",
        "repo": "ubisoft/ubisoft-laforge-animation-dataset",
        "rev": "master",  # resolved to a commit sha
        "zip": "lafan1/lafan1.zip",
        "members": [f"{c}.bvh" for c in LAFAN_CLIPS],
        "extra": {"license.txt": "license.txt"},
        "license": "CC BY-NC-ND 4.0",
        "usage": "내부 검증 전용. 재배포·파생물 공유 금지(리타겟 결과 포함).",
        "notes": "Unitree G1 csv와 같은 클립. 30 fps, Y-up, cm. zip(137 MB)에서 네 클립만 남기고 zip은 지웠다.",
    },
}


def http_get(url: str, accept_json: bool = False):
    req = urllib.request.Request(url, headers={"User-Agent": "retlens-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    return json.loads(data) if accept_json else data


def download(url: str, path: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "retlens-fetch/1.0"})
    tmp = path + ".part"
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    os.replace(tmp, path)


def git_blob_sha1(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def verify(path: str, algo: str, expected: str) -> str:
    got = git_blob_sha1(path) if algo == "git-sha1" else sha256(path)
    if got != expected:
        os.remove(path)
        raise RuntimeError(f"{os.path.basename(path)}: {algo} mismatch (got {got}, expected {expected})")
    return got


def fetch_github(spec: dict, out: str) -> tuple[str, list[dict]]:
    rev = spec["rev"]
    tree = http_get(f"https://api.github.com/repos/{spec['repo']}/git/trees/{rev}?recursive=1", True)
    shas = {t["path"]: t["sha"] for t in tree["tree"] if t["type"] == "blob"}
    rows = []
    for src, name in spec["files"].items():
        dst = os.path.join(out, name)
        if not (os.path.isfile(dst) and git_blob_sha1(dst) == shas[src]):
            download(f"https://raw.githubusercontent.com/{spec['repo']}/{rev}/{src}", dst)
        rows.append({"file": name, "source_path": src, "git-sha1": verify(dst, "git-sha1", shas[src])})
    return rev, rows


def fetch_hf(spec: dict, out: str) -> tuple[str, list[dict]]:
    info = http_get(f"https://huggingface.co/api/datasets/{spec['repo']}", True)
    rev = info["sha"]
    # hashes of just these paths (folder listings are paginated on large datasets)
    req = urllib.request.Request(
        f"https://huggingface.co/api/datasets/{spec['repo']}/paths-info/{rev}",
        data=json.dumps({"paths": list(spec["files"])}).encode(), method="POST",
        headers={"User-Agent": "retlens-fetch/1.0", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        entries = {e["path"]: e for e in json.loads(r.read())}
    rows = []
    for src, name in spec["files"].items():
        entry = entries[src]
        algo, expected = ("sha256", entry["lfs"]["oid"]) if entry.get("lfs") else ("git-sha1", entry["oid"])
        dst = os.path.join(out, name)
        if not os.path.isfile(dst):
            download(f"https://huggingface.co/datasets/{spec['repo']}/resolve/{rev}/{src}", dst)
        rows.append({"file": name, "source_path": src, algo: verify(dst, algo, expected)})
    return rev, rows


def fetch_lfs_zip(spec: dict, out: str) -> tuple[str, list[dict]]:
    commit = http_get(f"https://api.github.com/repos/{spec['repo']}/commits/{spec['rev']}", True)["sha"]
    pointer = http_get(f"https://raw.githubusercontent.com/{spec['repo']}/{commit}/{spec['zip']}").decode()
    fields = dict(line.split(" ", 1) for line in pointer.strip().splitlines())
    oid = fields["oid"].removeprefix("sha256:")
    rows = []
    missing = [m for m in spec["members"] if not os.path.isfile(os.path.join(out, m))]
    if missing:
        # the zip goes to a fresh temp folder and is deleted once the members are out
        with tempfile.TemporaryDirectory(prefix="lafan1_", dir=os.path.dirname(out)) as tmp:
            zpath = os.path.join(tmp, "lafan1.zip")
            print(f"  downloading {spec['zip']} ({int(fields['size']) / 2**20:.1f} MB) ...", flush=True)
            download(f"https://media.githubusercontent.com/media/{spec['repo']}/{commit}/{spec['zip']}", zpath)
            verify(zpath, "sha256", oid)
            with zipfile.ZipFile(zpath) as z:
                by_base = {os.path.basename(n): n for n in z.namelist() if not n.endswith("/")}
                for m in missing:
                    if m not in by_base:
                        raise RuntimeError(f"{m} not in {spec['zip']}")
                    with z.open(by_base[m]) as src, open(os.path.join(out, m), "wb") as dst:
                        dst.write(src.read())  # write under our own name: no paths from the archive
    for m in spec["members"]:
        rows.append({"file": m, "source_path": f"{spec['zip']}!{m}", "sha256": sha256(os.path.join(out, m))})
    for src, name in spec.get("extra", {}).items():
        dst = os.path.join(out, name)
        if not os.path.isfile(dst):
            download(f"https://raw.githubusercontent.com/{spec['repo']}/{commit}/{src}", dst)
        rows.append({"file": name, "source_path": src, "git-sha1": git_blob_sha1(dst)})
    rows.insert(0, {"file": "(deleted) lafan1.zip", "source_path": spec["zip"], "sha256": oid})
    return commit, rows


def write_source_md(key: str, spec: dict, rev: str, rows: list[dict], out: str) -> None:
    url = (f"https://huggingface.co/datasets/{spec['repo']}" if spec["host"] == "hf"
           else f"https://github.com/{spec['repo']}")
    lines = [
        f"# {spec['folder']}", "",
        f"- 출처: {url} (revision `{rev}`)",
        f"- 라이선스: {spec['license']}",
        f"- 사용 범위: **{spec['usage']}**",
        f"- 비고: {spec['notes']}",
        f"- 받은 날짜: {dt.date.today().isoformat()} (`python tools/fetch_samples.py {key}`)",
        "", "| 파일 | 원본 경로 | 해시 |", "|---|---|---|",
    ]
    for r in rows:
        algo = "git-sha1" if "git-sha1" in r else "sha256"
        lines.append(f"| {r['file']} | {r['source_path']} | {algo} `{r[algo]}` |")
    with open(os.path.join(out, "SOURCE.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sets", nargs="*", help=f"any of {', '.join(SETS)} (default: all)")
    args = ap.parse_args()
    unknown = sorted(set(args.sets) - set(SETS))
    if unknown:
        ap.error(f"unknown set(s): {', '.join(unknown)}")
    fetchers = {"github": fetch_github, "hf": fetch_hf, "github_lfs_zip": fetch_lfs_zip}
    for key in args.sets or list(SETS):
        spec = SETS[key]
        out = os.path.join(RAW, spec["folder"])
        os.makedirs(out, exist_ok=True)
        print(f"[{key}] -> {out}", flush=True)
        rev, rows = fetchers[spec["host"]](spec, out)
        write_source_md(key, spec, rev, rows, out)
        print(f"[{key}] {len(rows)} file(s) verified, revision {rev[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
