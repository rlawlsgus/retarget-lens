"""Balance on / off in MuJoCo: replay robot motions with no controller (open-loop PD, like
`isaac_replay.py --physics --assist 0`) and with GMT, a pretrained general tracking policy that keeps
its balance the way a deployed tracker does (retlens/policy_replay.py; scripts/install_gmt.ps1).

    python tools/policy_replay.py data/retargeted/cmu_fbx/02_01_g1.npz
    python tools/policy_replay.py data/raw/cmu_bvh/02_01.bvh --swing-clearance 2   # human motion: retargeted (cached)
    python tools/policy_replay.py data/raw/cmu_fbx --controller gmt --video --out-dir reports/policy/cmu_fbx
    python tools/policy_replay.py --gmt-sample walk_stand                          # GMT's own example motion
    python tools/policy_replay.py --summary reports/policy                         # rebuild summary.md only

Per clip and controller it writes <out-dir>/<folder>/<clip>_<controller>_sim.npz (the simulated motion,
50 Hz; RetLens opens it next to the original) and .json (falls, tracking errors, policy correction,
torque saturation), --video one MP4 per clip with the controllers side by side and the reference as a
blue ghost. summary.md collects every result under --out-dir.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import pickle
import shutil
import subprocess
import sys
import time

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

from retlens import policy_replay as pr  # noqa: E402
from retlens.motion import RobotMotion  # noqa: E402

MOTION_EXT = (".bvh", ".fbx", ".npz", ".csv", ".pkl")


def log(msg) -> None:
    print(f"[policy_replay] {msg}", flush=True)


class _NumpyOnly(pickle.Unpickler):
    """GMT's example motions are pickles of numpy arrays: refuse anything else."""

    OK = {("numpy.core.multiarray", "_reconstruct"), ("numpy._core.multiarray", "_reconstruct"),
          ("numpy", "ndarray"), ("numpy", "dtype")}

    def find_class(self, module, name):
        if (module, name) not in self.OK:
            raise pickle.UnpicklingError(f"refusing {module}.{name} in a motion pickle")
        return super().find_class(module.replace("numpy.core", "numpy._core"), name)


def gmt_sample(name: str) -> RobotMotion:
    path = os.path.join(pr.gmt_dir(), "assets", "motions", name if name.endswith(".pkl") else name + ".pkl")
    with open(path, "rb") as f:
        d = _NumpyOnly(f).load()
    q = np.asarray(d["root_rot"], dtype=np.float64)
    return RobotMotion(name=os.path.splitext(os.path.basename(path))[0], joint_names=list(pr.GMT_DOFS),
                       root_pos=np.asarray(d["root_pos"], dtype=np.float64),
                       root_quat=np.concatenate([q[:, 3:4], q[:, :3]], axis=1),
                       dof_pos=np.asarray(d["dof_pos"], dtype=np.float64), fps=float(d["fps"]), source=path)


def expand(inputs: list[str]) -> list[str]:
    out = []
    for p in inputs:
        if os.path.isdir(p):
            for r, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d.lower() != "cache"]
                out += [os.path.join(r, f) for f in sorted(files) if f.lower().endswith(MOTION_EXT)
                        and not f.endswith(("_stagei.npz", "_sim.npz"))]
        else:
            out.append(p)
    return out


# ------------------------------------------------------------------------------------------ video
def _font(size: int):
    from PIL import ImageFont

    for f in (r"C:\Windows\Fonts\malgun.ttf", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"):
        if os.path.isfile(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def render_video(results: list, ref: pr.Reference, model_path: str, out: str, title: str,
                 size=(480, 640), fps: int = 25) -> str | None:
    """One panel per controller: the simulated robot, the reference as a blue ghost at its pelvis."""
    import mujoco
    from PIL import Image, ImageDraw

    ffmpeg = shutil.which("ffmpeg") or (r"C:\ffmpeg\bin\ffmpeg.exe" if os.path.isfile(r"C:\ffmpeg\bin\ffmpeg.exe") else None)
    if not ffmpeg:
        log("no ffmpeg on PATH: video skipped")
        return None
    model = mujoco.MjModel.from_xml_path(model_path)
    h, w = size
    renderer = mujoco.Renderer(model, h, w)
    sim_d, ref_d = mujoco.MjData(model), mujoco.MjData(model)
    q_adr = model.jnt_qposadr[-len(pr.GMT_DOFS):]
    ghost_opt, pert = mujoco.MjvOption(), mujoco.MjvPerturb()
    ghost_opt.geomgroup[:] = [0, 1, 0, 0, 0, 0]  # the visual meshes only (group 0 holds the collision copies)
    ghost_opt.sitegroup[:] = 0
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.distance, cam.azimuth, cam.elevation = 3.2, 135.0, -12.0
    font, small = _font(18), _font(15)
    step = max(1, int(round(1.0 / (pr.CONTROL_DT * fps))))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    proc = subprocess.Popen([ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                             "-s", f"{w * len(results)}x{h}", "-r", str(fps), "-i", "-", "-c:v", "libx264",
                             "-pix_fmt", "yuv420p", "-crf", "23", out], stdin=subprocess.PIPE,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    n = min(len(r.times) for r in results)
    try:
        for k in range(0, n, step):
            t = results[0].times[k]
            pos, rot, _, _, dof, _ = (a[0] for a in ref.frame([t]))
            panels = []
            for res in results:
                sim_d.qpos[:3], sim_d.qpos[3:7], sim_d.qpos[q_adr] = res.root_pos[k], res.root_quat[k], res.dof_pos[k]
                mujoco.mj_kinematics(model, sim_d)
                ref_d.qpos[:3] = [res.root_pos[k][0], res.root_pos[k][1], pos[2]]
                ref_d.qpos[3:7] = [rot[3], rot[0], rot[1], rot[2]]
                ref_d.qpos[q_adr] = dof
                mujoco.mj_kinematics(model, ref_d)
                cam.lookat[:] = [res.root_pos[k][0], res.root_pos[k][1], 0.7]
                renderer.update_scene(sim_d, camera=cam)
                scn = renderer.scene
                n0 = scn.ngeom
                mujoco.mjv_addGeoms(model, ref_d, ghost_opt, pert, mujoco.mjtCatBit.mjCAT_DYNAMIC, scn)
                for g in range(n0, scn.ngeom):
                    scn.geoms[g].rgba[:] = [0.25, 0.55, 1.0, 0.3]
                img = Image.fromarray(renderer.render())
                dr = ImageDraw.Draw(img)
                falls = sum(1 for ft in res.metrics["fall_times_s"] + res.metrics.get("hold_fall_times_s", []) if ft <= t)
                dr.text((10, 8), pr.LABELS[res.controller], font=font, fill=(255, 255, 255))
                dr.text((10, 32), f"{title}  t={t:5.2f}s  넘어짐 {falls}", font=small, fill=(230, 230, 230))
                panels.append(np.asarray(img))
            proc.stdin.write(np.concatenate(panels, axis=1).tobytes())
        proc.stdin.close()
        proc.wait()
    except OSError as e:  # ffmpeg quit early (broken pipe)
        proc.kill()
        proc.wait()
        log(f"video failed ({out}): {e}")
        return None
    finally:
        renderer.close()
    if proc.returncode != 0:
        log(f"ffmpeg exited with {proc.returncode}: {out}")
        return None
    return out


# ---------------------------------------------------------------------------------------- summary
def write_summary(out_dir: str) -> str:
    rows = []
    for j in sorted(glob.glob(os.path.join(out_dir, "**", "*_sim.json"), recursive=True)):
        with open(j, encoding="utf-8") as f:
            info = json.load(f)
        m = info.get("policy_replay")
        if m:
            rows.append((info, m))
    order = {c: i for i, c in enumerate(pr.CONTROLLERS)}  # per clip: off, then on
    rows.sort(key=lambda r: (r[0].get("label", ""), r[0].get("kind", ""), order.get(r[1].get("controller"), 9)))
    fmt = lambda v, f="{:.1f}": "-" if v is None else f.format(v)  # noqa: E731
    lines = [f"# 균형 켬 / 끔 비교 (MuJoCo, {time.strftime('%Y-%m-%d %H:%M')})", "",
             "같은 클립을 같은 G1 모델(GMT의 23 DoF G1, 1 kHz)에서 두 가지로 돌린 결과입니다. "
             "**제어기 없음**: 리타겟 관절각을 높은 게인의 PD로 그대로 따라감(Isaac `--physics --assist 0`과 같은 개루프 재생). "
             "**추적 정책 (GMT)**: 공개된 G1 범용 추적 정책이 기준 동작과 자기 상태를 보고 관절 목표를 냄(실제 로봇의 방식). "
             "보조 힘(하네스)은 둘 다 없습니다. 넘어지면(기울기 60°, 골반 0.3 m 아래, 원본보다 0.25 m 낮음) 그 시각의 원본 자세로 다시 시작해 셉니다. "
             "넘어짐 괄호 안은 클립이 끝난 뒤 마지막 자세로 1초 서 있는 동안의 넘어짐입니다. "
             "관절 RMSE: 23관절(다리 12관절). 몸 위치 오차: 골반 기준 몸통·무릎·발목·팔꿈치·손 위치 차의 평균. "
             "정책 보정: 정책이 낸 관절 목표와 원본 관절각의 평균 차이. 토크 한계: 요구 토크가 한계를 넘은 스텝 비율. "
             f"`tools/policy_replay.py`가 만듭니다.", "",
             "| 클립 | 종류 | 제어 | 길이 s | 넘어짐 | 첫 넘어짐 s | 관절 RMSE° (다리) | 몸 위치 오차 cm | 골반 높이 오차 cm | 정책 보정 ° | 토크 한계 % |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for info, m in rows:
        lines.append("| {} | {} | {} | {} | {} | {} | {} ({}) | {} | {} | {} | {} |".format(
            info.get("label", "?"), info.get("kind", ""), pr.LABELS.get(m["controller"], m["controller"]),
            fmt(m.get("clip_s")), f"{m['falls']}" + (f" (+{m['hold_falls']})" if m.get("hold_falls") else ""),
            fmt(m.get("first_fall_s"), "{:.2f}"),
            fmt(m.get("joint_rmse_deg")), fmt(m.get("leg_joint_rmse_deg")), fmt(m.get("body_error_cm")),
            fmt(m.get("pelvis_height_error_cm")), fmt(m.get("policy_correction_deg")),
            fmt(100 * m["torque_saturated_ratio"] if m.get("torque_saturated_ratio") is not None else None)))
    path = os.path.join(out_dir, "summary.md")
    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


# ------------------------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", help="robot motions (npz / csv / pkl) or human motions (bvh / fbx / AMASS npz)")
    ap.add_argument("--controller", nargs="+", choices=pr.CONTROLLERS, default=list(pr.CONTROLLERS))
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "reports", "policy"))
    ap.add_argument("--smooth", type=float, default=6.0, help="human inputs: smoothing (Hz, 0 = off)")
    ap.add_argument("--swing-clearance", type=float, default=0.0, metavar="CM", help="human inputs: swing feet >= CM")
    ap.add_argument("--hold", type=float, default=1.0, help="seconds on the last frame after the clip")
    ap.add_argument("--video", action="store_true", help="MP4 per clip, controllers side by side")
    ap.add_argument("--gmt-sample", nargs="+", default=[], metavar="NAME", help="GMT's example motions (e.g. walk_stand)")
    ap.add_argument("--summary", default=None, metavar="DIR", help="only rebuild DIR/summary.md")
    args = ap.parse_args()

    if args.summary:
        log(f"wrote {write_summary(args.summary)}")
        return 0
    files = pr.gmt_files()
    clips = []  # (folder, name, label, kind, RobotMotion, Reference, source)
    skipped, used = [], set()

    def add(folder, name, label, kind, motion, source):
        ref = pr.Reference.from_motion(motion)  # raises for motions without the G1 joints
        key = (folder, name)
        if key in used:  # e.g. the BVH and the FBX of one take in one folder
            name = f"{name}_{os.path.splitext(source)[1][1:].lower() or 'motion'}"
            n = 2
            while (folder, name) in used:
                name, n = f"{name}_{n}", n + 1
            log(f"{label}: saved as {name} (same name as an earlier input)")
        used.add((folder, name))
        clips.append((folder, name, label, kind, motion, ref, source))

    for sample in args.gmt_sample:
        m = gmt_sample(sample)
        add("gmt_samples", m.name, f"gmt_samples/{m.name}", "GMT 예제 (GMT 자체 리타겟)", m, m.source)
    if args.inputs:
        from retlens import settings
        from retlens.compare import load_item

        smpl = settings.find_smpl().path
        for path in expand(args.inputs):
            try:
                item = load_item(path, smooth=args.smooth, swing_clearance=args.swing_clearance / 100.0,
                                 smpl_model_dir=smpl, log=log)
                folder, name = item.label.split("/", 1) if "/" in item.label else ("", item.label)
                add(folder, name.replace("/", "_"), item.label, item.kind, item.robot, os.path.abspath(path))
            except Exception as e:  # e.g. metadata.csv next to the clips: not a motion
                log(f"skipped {path}: {type(e).__name__}: {e}")
                skipped.append(path)
    if not clips:
        ap.error("give motion files, --gmt-sample or --summary")

    for folder, name, label, kind, motion, ref, source in clips:
        results = []
        try:
            for c in args.controller:
                sim = pr.G1Sim(files["model"], c, policy_path=files["policy"])
                t0 = time.time()
                res = pr.run(sim, ref, hold_s=args.hold)
                m = res.metrics
                out = os.path.join(args.out_dir, folder, f"{name}_{c}_sim.npz")
                pr.save_result(res, out, motion.joint_names, {
                    "label": label, "kind": kind, "source": source, "controller_label": pr.LABELS[c],
                    "model": "GMT G1 (23 DoF, wrists fixed), MuJoCo 1 kHz", "gmt_files": files,
                    "swing_clearance_cm": args.swing_clearance, "smooth_hz": args.smooth})
                log(f"{label} [{c}] {ref.length:.1f}s in {time.time() - t0:.1f}s: falls {m['falls']}"
                    f"{' (first ' + str(m['first_fall_s']) + ' s)' if m['falls'] else ''}"
                    f"{', +' + str(m['hold_falls']) + ' in the hold' if m['hold_falls'] else ''}, "
                    f"joint RMSE {m['joint_rmse_deg']} deg, body error {m['body_error_cm']} cm, "
                    f"torque-limited {100 * m['torque_saturated_ratio']:.1f}%")
                results.append(res)
        except Exception as e:
            log(f"failed {label}: {type(e).__name__}: {e}")
            skipped.append(source)
            continue
        if args.video:
            v = render_video(results, ref, files["model"], os.path.join(args.out_dir, folder, f"{name}_balance.mp4"), label)
            log(f"video {v}" if v else f"video skipped for {label}")
    log(f"wrote {write_summary(args.out_dir)}")
    if skipped:
        log(f"{len(skipped)} input(s) skipped: {', '.join(os.path.basename(p) for p in skipped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
