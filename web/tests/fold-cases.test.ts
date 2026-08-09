// ER-9 folding-case unit tests — pure geometry + id resolution.
// Run via `npm run test:node` (compiled with tsc into dist/node-tests).
import test from "node:test";
import assert from "node:assert/strict";

import {
  FOLD_CASES,
  resolveFoldCase,
  computeFaceGeometry,
} from "../components/chat/3d/fold-cases";

// ---------------------------------------------------------------------------
// resolveFoldCase — id lookup must tolerate prefixes / whitespace / case
// ---------------------------------------------------------------------------

test("resolveFoldCase defaults to cube for empty input", () => {
  assert.equal(resolveFoldCase(undefined).id, "cube");
  assert.equal(resolveFoldCase(null).id, "cube");
  assert.equal(resolveFoldCase("").id, "cube");
  assert.equal(resolveFoldCase("   ").id, "cube");
});

test("resolveFoldCase matches plain ids", () => {
  assert.equal(resolveFoldCase("cube").id, "cube");
  assert.equal(resolveFoldCase("rect_prism").id, "rect_prism");
  assert.equal(resolveFoldCase("triangular_prism").id, "triangular_prism");
  assert.equal(resolveFoldCase("square_pyramid").id, "square_pyramid");
});

test("resolveFoldCase strips er3d: prefix (regression for the review bug)", () => {
  assert.equal(resolveFoldCase("er3d:square_pyramid").id, "square_pyramid");
  assert.equal(resolveFoldCase("er3d:cube").id, "cube");
  assert.equal(resolveFoldCase("er3d:rect_prism").id, "rect_prism");
  // Trailing fence text / stray words after the id are ignored.
  assert.equal(resolveFoldCase("er3d:cube hello world").id, "cube");
});

test("resolveFoldCase is case-insensitive and trims", () => {
  assert.equal(resolveFoldCase("  CUBE  ").id, "cube");
  assert.equal(resolveFoldCase("ER3D:SQUARE_PYRAMID").id, "square_pyramid");
});

test("resolveFoldCase falls back to cube for unknown ids", () => {
  assert.equal(resolveFoldCase("nope").id, "cube");
  assert.equal(resolveFoldCase("er3d:icosahedron").id, "cube");
});

// ---------------------------------------------------------------------------
// computeFaceGeometry — centroid / fan triangulation / unit normal
// ---------------------------------------------------------------------------

const SQUARE: [number, number, number][] = [
  [-0.5, -0.5, 0],
  [0.5, -0.5, 0],
  [0.5, 0.5, 0],
  [-0.5, 0.5, 0],
];

test("computeFaceGeometry square: centroid at origin, CCW normal +z", () => {
  const g = computeFaceGeometry(SQUARE);
  assert.equal(g.count, 4);
  assert.deepEqual(g.centroid, [0, 0, 0]);
  assert.deepEqual(g.indices, [0, 1, 2, 0, 2, 3]);
  // local verts are zero-centered.
  const sum = [0, 0, 0];
  for (let i = 0; i < g.count; i++) {
    sum[0] += g.localVerts[i * 3];
    sum[1] += g.localVerts[i * 3 + 1];
    sum[2] += g.localVerts[i * 3 + 2];
  }
  assert.ok(Math.abs(sum[0]) < 1e-9 && Math.abs(sum[1]) < 1e-9 && Math.abs(sum[2]) < 1e-9);
  // CCW winding in the z=0 plane → normal +z.
  assert.ok(Math.abs(g.normal[0]) < 1e-9 && Math.abs(g.normal[1]) < 1e-9);
  assert.equal(g.normal[2], 1);
});

test("computeFaceGeometry triangle: single fan triangle", () => {
  const tri: [number, number, number][] = [
    [-0.5, -0.2887, 0],
    [0.5, -0.2887, 0],
    [0, 0.5774, 0],
  ];
  const g = computeFaceGeometry(tri);
  assert.equal(g.count, 3);
  assert.deepEqual(g.indices, [0, 1, 2]);
  const len = Math.hypot(g.normal[0], g.normal[1], g.normal[2]);
  assert.ok(Math.abs(len - 1) < 1e-9, "normal must be unit length");
});

test("computeFaceGeometry normal is unit length for all cases/faces", () => {
  for (const c of FOLD_CASES) {
    for (const f of c.faces) {
      const g = computeFaceGeometry(f.foldedVerts);
      const len = Math.hypot(g.normal[0], g.normal[1], g.normal[2]);
      assert.ok(Math.abs(len - 1) < 1e-9, `${c.id}/${f.id} normal not unit`);
      // fan triangulation index count = 3 * (n - 2)
      assert.equal(g.indices.length, 3 * (g.count - 2), `${c.id}/${f.id} indices`);
      assert.equal(g.localVerts.length, g.count * 3, `${c.id}/${f.id} localVerts`);
    }
  }
});

test("computeFaceGeometry centroid equals vertex mean for a prism side", () => {
  // CCW winding seen from +y (side face on the y=0.5 plane, height along z).
  const side: [number, number, number][] = [
    [-0.5, 0.5, 0],
    [-0.5, 0.5, 1],
    [0.5, 0.5, 1],
    [0.5, 0.5, 0],
  ];
  const g = computeFaceGeometry(side);
  assert.deepEqual(g.centroid, [0, 0.5, 0.5]);
  // Side face normal points +y.
  assert.ok(Math.abs(g.normal[0]) < 1e-9 && Math.abs(g.normal[2]) < 1e-9);
  assert.equal(g.normal[1], 1);
});

test("FOLD_CASES data integrity: unique ids, >=3 verts per face", () => {
  const ids = FOLD_CASES.map((c) => c.id);
  assert.equal(new Set(ids).size, ids.length, "case ids must be unique");
  for (const c of FOLD_CASES) {
    assert.ok(c.faces.length >= 4, `${c.id} needs at least 4 faces`);
    const faceIds = c.faces.map((f) => f.id);
    assert.equal(new Set(faceIds).size, faceIds.length, `${c.id} face ids unique`);
    for (const f of c.faces) {
      assert.ok(f.foldedVerts.length >= 3, `${c.id}/${f.id} needs >=3 verts`);
      assert.ok(f.order >= 0, `${c.id}/${f.id} order >= 0`);
    }
  }
});
