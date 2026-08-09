/**
 * Minimal ambient type declarations for three (0.185) + OrbitControls.
 *
 * three ships without bundled .d.ts (types live in the separate @types/three
 * package). Installing it requires a network npm run, which is unreliable in
 * this environment, so we declare just the API surface Folding3DViewer uses.
 * Keep this file in sync with the component's usage.
 */

declare module "three" {
  export class Vector3 {
    constructor(x?: number, y?: number, z?: number);
    x: number;
    y: number;
    z: number;
    set(x: number, y: number, z: number): this;
    copy(v: Vector3): this;
    multiplyScalar(n: number): this;
    lerpVectors(a: Vector3, b: Vector3, t: number): this;
  }

  export class Quaternion {
    constructor(x?: number, y?: number, z?: number, w?: number);
    setFromUnitVectors(from: Vector3, to: Vector3): this;
    setFromAxisAngle(axis: Vector3, angle: number): this;
    copy(q: Quaternion): this;
    slerpQuaternions(a: Quaternion, b: Quaternion, t: number): this;
  }

  export class Object3D {
    position: Vector3;
    quaternion: Quaternion;
    add(...objects: Object3D[]): this;
    remove(...objects: Object3D[]): this;
  }

  export class Scene extends Object3D {
    background: unknown;
  }

  export class PerspectiveCamera extends Object3D {
    constructor(
      fov?: number,
      aspect?: number,
      near?: number,
      far?: number,
    );
    aspect: number;
    lookAt(x: number, y: number, z: number): void;
    updateProjectionMatrix(): void;
  }

  export class WebGLRenderer {
    constructor(parameters?: Record<string, unknown>);
    domElement: HTMLCanvasElement;
    setPixelRatio(value: number): void;
    setSize(width: number, height: number): void;
    render(scene: Scene, camera: PerspectiveCamera): void;
    dispose(): void;
  }

  export class BufferAttribute {
    constructor(array: Float32Array | number[], itemSize: number);
  }

  export class BufferGeometry {
    setAttribute(name: string, attribute: BufferAttribute): this;
    setIndex(indices: number[] | BufferAttribute): this;
    computeVertexNormals(): void;
  }

  export class EdgesGeometry extends BufferGeometry {
    constructor(geometry?: BufferGeometry, thresholdAngle?: number);
  }

  export class Material {
    transparent?: boolean;
  }

  export class MeshStandardMaterial extends Material {
    constructor(parameters?: Record<string, unknown>);
  }

  export class LineBasicMaterial extends Material {
    constructor(parameters?: Record<string, unknown>);
  }

  export class LineSegments extends Object3D {
    constructor(geometry?: BufferGeometry, material?: Material);
  }

  export class Mesh extends Object3D {
    constructor(geometry?: BufferGeometry, material?: Material);
  }

  export class AmbientLight extends Object3D {
    constructor(color?: unknown, intensity?: number);
  }

  export class DirectionalLight extends Object3D {
    constructor(color?: unknown, intensity?: number);
  }

  export class GridHelper extends Object3D {
    constructor(
      size?: number,
      divisions?: number,
      color1?: unknown,
      color2?: unknown,
    );
  }

  export class Clock {
    getDelta(): number;
  }

  export const DoubleSide: number;
  export const Color: new (value?: unknown) => { value: unknown };
}
