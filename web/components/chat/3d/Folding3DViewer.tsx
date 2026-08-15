"use client";

import i18n from "i18next";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Loader2, Pause, Play, RotateCcw } from "lucide-react";

// Type-only namespace: three is loaded at runtime via dynamic import() inside
// the scene effect; this import is erased at build time and only provides the
// `THREE.Xxx` type annotations used below.
import type * as THREE from "three";

import {
  FOLD_CASES,
  computeFaceGeometry,
  resolveFoldCase,
  type FoldCase,
} from "./fold-cases";

/** Chinese-first inline translation helper (mirrors the other ER surfaces). */
const tr = (zh: string, en: string) =>
  i18n.language?.toLowerCase().startsWith("zh") ? zh : en;

// three is ESM-only; dynamic import keeps it out of the SSR bundle and lets
// the scene initialize strictly in the browser.
type ThreeModule = typeof import("three");
type ThreeOrbit = typeof import("three/examples/jsm/controls/OrbitControls.js");

const SCENE_SCALE = 1.4;

/** 解析 ```er3d:case_id 围栏的 case id。 */
export function parseFoldScript(script: string | null | undefined): string {
  const raw = (script || "").trim();
  const firstLine = raw.split(/\r?\n/)[0].trim();
  const inline = /^(?:er3d:)?([A-Za-z_][\w-]*)/.exec(firstLine);
  return inline?.[1] ?? "cube";
}

export interface Folding3DViewerProps {
  /** ```er3d:case_id 围栏内容（第一行可为 `cube` / `er3d:cube`）。 */
  script?: string;
  /** 可选的案例 id（优先于 script 解析）。 */
  caseId?: string;
  title?: string;
  height?: number;
  autoPlay?: boolean;
  className?: string;
}

export function Folding3DViewer({
  script,
  caseId,
  title,
  height = 420,
  autoPlay = true,
  className = "",
}: Folding3DViewerProps) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [playing, setPlaying] = useState(autoPlay);
  const [three, setThree] = useState<ThreeModule | null>(null);
  const [orbit, setOrbit] = useState<ThreeOrbit | null>(null);
  const [loadError, setLoadError] = useState(false);

  // Playback state mirrored into a ref so the rAF loop (created once, inside
  // the scene effect) always reads the live value without re-creating itself.
  const playingRef = useRef(playing);
  useEffect(() => {
    playingRef.current = playing;
  }, [playing]);

  // Fold progress (0..1), hoisted into a ref so both the rAF loop and the
  // reset callback can reach it (a plain local would be trapped in the effect
  // closure, leaving the reset button a no-op after the first fold).
  const tRef = useRef(0);

  // Lazy-load three only in the browser.
  useEffect(() => {
    let active = true;
    Promise.all([
      import("three"),
      import("three/examples/jsm/controls/OrbitControls.js"),
    ])
      .then(([m, oc]) => {
        if (active) {
          setThree(m);
          setOrbit(oc);
        }
      })
      .catch(() => active && setLoadError(true));
    return () => {
      active = false;
    };
  }, []);

  const resolvedId = useMemo(
    () => caseId ?? parseFoldScript(script),
    [caseId, script],
  );
  const foldCase = useMemo(() => resolveFoldCase(resolvedId), [resolvedId]);

  // Scene lifecycle — created once three is loaded.
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount || !three || !orbit) return;
    const THREE = three;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#0f172a");
    const camera = new THREE.PerspectiveCamera(
      45,
      mount.clientWidth / Math.max(mount.clientHeight, 1),
      0.1,
      50,
    );
    camera.position.set(2.6, 1.8, 3.2);
    camera.lookAt(0, 0.4, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);

    scene.add(new THREE.AmbientLight(0xffffff, 0.85));
    const key = new THREE.DirectionalLight(0xffffff, 1.1);
    key.position.set(3, 5, 2);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x88aaff, 0.5);
    rim.position.set(-3, -1, -2);
    scene.add(rim);

    // Ground grid for spatial reference.
    const grid = new THREE.GridHelper(4, 12, 0x334155, 0x1e293b);
    grid.position.y = -0.9;
    scene.add(grid);

    const controls = new orbit.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 1.6;
    controls.target.set(0, 0.4, 0);
    controls.minDistance = 1.5;
    controls.maxDistance = 8;

    // Build one mesh per face. Geometry is shared between flat/folded poses —
    // only the Object3D pose is interpolated.
    const meshes: {
      mesh: THREE.Mesh;
      flatPos: THREE.Vector3;
      flatQuat: THREE.Quaternion;
      foldedPos: THREE.Vector3;
      foldedQuat: THREE.Quaternion;
      order: number;
    }[] = [];

    const Z_AXIS = new THREE.Vector3(0, 0, 1);

    for (const face of foldCase.faces) {
      const geo = computeFaceGeometry(face.foldedVerts);
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute(
        "position",
        new THREE.BufferAttribute(geo.localVerts, 3),
      );
      geometry.setIndex(geo.indices);
      geometry.computeVertexNormals();

      const material = new THREE.MeshStandardMaterial({
        color: face.color,
        side: THREE.DoubleSide,
        roughness: 0.55,
        metalness: 0.05,
      });
      const mesh = new THREE.Mesh(geometry, material);

      // Folded pose: centroid + normal alignment.
      const foldedPos = new THREE.Vector3(...geo.centroid).multiplyScalar(
        SCENE_SCALE,
      );
      const foldedQuat = new THREE.Quaternion().setFromUnitVectors(
        Z_AXIS,
        new THREE.Vector3(...geo.normal),
      );
      // Flat pose: laid on the z=0 plane at the case's net position.
      const ry = (face.flat.ry ?? 0) * (Math.PI / 180);
      const flatPos = new THREE.Vector3(
        face.flat.x * SCENE_SCALE,
        face.flat.y * SCENE_SCALE,
        0,
      );
      const flatQuat = new THREE.Quaternion().setFromAxisAngle(
        new THREE.Vector3(0, 1, 0),
        ry,
      );

      // Edge highlight for crease readability.
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(geometry),
        new THREE.LineBasicMaterial({ color: 0x1e293b, linewidth: 1 }),
      );
      mesh.add(edges);

      mesh.position.copy(flatPos);
      mesh.quaternion.copy(flatQuat);
      scene.add(mesh);
      meshes.push({
        mesh,
        flatPos,
        flatQuat,
        foldedPos,
        foldedQuat,
        order: face.order,
      });
    }

    // Animation loop: t ∈ [0,1]; each face starts at its own order stagger.
    let raf = 0;
    const clock = new THREE.Clock();
    const loop = () => {
      raf = requestAnimationFrame(loop);
      const delta = Math.min(clock.getDelta(), 0.05);
      if (playingRef.current && tRef.current < 1) {
        tRef.current = Math.min(1, tRef.current + delta * 0.9);
      }
      const ease = (u: number) =>
        u <= 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2;
      for (const f of meshes) {
        const local =
          (tRef.current - f.order * 0.18) / (1 - f.order * 0.18 || 1);
        const u = Math.min(1, Math.max(0, local));
        const e = ease(u);
        f.mesh.position.lerpVectors(f.flatPos, f.foldedPos, e);
        f.mesh.quaternion.slerpQuaternions(f.flatQuat, f.foldedQuat, e);
      }
      controls.update();
      renderer.render(scene, camera);
    };

    const onResize = () => {
      const w = mount.clientWidth;
      const h = mount.clientHeight;
      camera.aspect = w / Math.max(h, 1);
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener("resize", onResize);
    loop();

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      controls.dispose();
      // Free per-face GPU resources (geometries + materials + edge lines) and
      // drop the WebGL context — the effect re-runs per foldCase.id, so each
      // case switch would otherwise leak a fresh set of buffers/materials.
      for (const f of meshes) {
        f.mesh.traverse((obj) => {
          const node = obj as THREE.Mesh;
          if (node.geometry) node.geometry.dispose();
          const mat = node.material as
            | THREE.Material
            | THREE.Material[]
            | undefined;
          if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
          else if (mat) mat.dispose();
        });
      }
      grid.geometry.dispose();
      const gridMat = grid.material as THREE.Material | THREE.Material[];
      if (Array.isArray(gridMat)) gridMat.forEach((m) => m.dispose());
      else gridMat.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      mount.removeChild(renderer.domElement);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [three, orbit, foldCase.id]);

  const reset = useCallback(() => {
    tRef.current = 0;
    playingRef.current = true;
    setPlaying(true);
  }, []);

  return (
    <div
      className={`overflow-hidden rounded-xl border border-[var(--border)]/70 bg-[#0f172a] ${className}`}
      style={{ height }}
    >
      <div className="flex items-center justify-between gap-2 border-b border-white/10 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-[12.5px] font-medium text-white/90">
            {title || `${foldCase.nameZh} · 3D 翻折演示`}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={() => setPlaying((v) => !v)}
            title={playing ? tr("暂停", "Pause") : tr("播放", "Play")}
            aria-label={playing ? tr("暂停", "Pause") : tr("播放", "Play")}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-white/70 transition-colors hover:bg-white/10 hover:text-white"
          >
            {playing ? (
              <Pause size={15} strokeWidth={2} />
            ) : (
              <Play size={15} strokeWidth={2} />
            )}
          </button>
          <button
            type="button"
            onClick={reset}
            title={tr("重置", "Reset")}
            aria-label={tr("重置", "Reset")}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-white/70 transition-colors hover:bg-white/10 hover:text-white"
          >
            <RotateCcw size={15} strokeWidth={2} />
          </button>
        </div>
      </div>
      <div ref={mountRef} className="relative h-[calc(100%-37px)] w-full">
        {loadError && (
          <div className="absolute inset-0 flex items-center justify-center text-[12.5px] text-white/70">
            {tr("3D 引擎加载失败", "Failed to load the 3D engine")}
          </div>
        )}
        {!three && !loadError && (
          <div className="absolute inset-0 flex items-center justify-center gap-2 text-[12.5px] text-white/70">
            <Loader2 size={15} className="animate-spin" />
            {tr("正在加载 3D 场景…", "Loading 3D scene…")}
          </div>
        )}
      </div>
      <div className="border-t border-white/10 px-3 py-1.5 text-[11px] leading-snug text-white/55">
        {foldCase.hintZh}
        <span className="opacity-60"> · 拖拽旋转 · 滚轮缩放</span>
      </div>
    </div>
  );
}

/** 案例选择器（供手动演示入口复用）。 */
export function FoldCasePicker({
  value,
  onSelect,
}: {
  value: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {FOLD_CASES.map((c: FoldCase) => (
        <button
          key={c.id}
          type="button"
          onClick={() => onSelect(c.id)}
          className={`rounded-xl border px-3 py-2 text-left transition-colors ${
            value === c.id
              ? "border-[var(--primary)] bg-[var(--primary)]/[0.07]"
              : "border-[var(--border)]/60 hover:bg-[var(--muted)]/40"
          }`}
        >
          <div className="text-[12.5px] font-medium text-[var(--foreground)]">
            {c.nameZh}
          </div>
          <div className="mt-0.5 text-[11px] leading-snug text-[var(--muted-foreground)]">
            {c.hintZh}
          </div>
        </button>
      ))}
    </div>
  );
}
