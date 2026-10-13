// Route network for the mobile units. The twins publish a position every 2 s,
// and at 60 simulated seconds per real second a truck passes more than one leg
// of a decline between two samples. A straight tween would cut through rock, so
// the scene moves each unit along the shortest path over the drawn workings
// (declines, level drives, accesses, crosscuts, surface haul roads).

const TOLERANCE = 1.5;      // m: a polyline end this close to a segment joins it
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

function closestOnSegment(p, a, b) {
  const ab = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  const len2 = ab[0] * ab[0] + ab[1] * ab[1] + ab[2] * ab[2];
  let t = len2 ? ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1] + (p[2] - a[2]) * ab[2]) / len2 : 0;
  t = Math.max(0, Math.min(1, t));
  const point = [a[0] + ab[0] * t, a[1] + ab[1] * t, a[2] + ab[2] * t];
  return { t, point, d: dist(p, point) };
}

export function buildNetwork(geometry) {
  const polylines = [];
  for (const object of Object.values(geometry.objects || {})) {
    if (object.kind === 'decline' && Array.isArray(object.points)) polylines.push(object.points);
    if (object.kind === 'level') {
      if (Array.isArray(object.points)) polylines.push(object.points);
      for (const link of object.links || []) {
        if (link.role !== 'airway' && Array.isArray(link.points)) polylines.push(link.points);
      }
    }
  }
  for (const [name, item] of Object.entries(geometry.scenery || {})) {
    if (name.startsWith('road') && Array.isArray(item.points)) polylines.push(item.points);
  }

  // Split every segment at the vertices of other polylines that touch it.
  const vertices = polylines.flat();
  const pieces = [];
  for (const line of polylines) {
    for (let i = 0; i < line.length - 1; i += 1) {
      const a = line[i];
      const b = line[i + 1];
      const cuts = [];
      for (const v of vertices) {
        const hit = closestOnSegment(v, a, b);
        if (hit.d < TOLERANCE && hit.t > 1e-3 && hit.t < 1 - 1e-3) cuts.push(hit);
      }
      cuts.sort((p, q) => p.t - q.t);
      let from = a;
      for (const cut of cuts) {
        if (dist(from, cut.point) > 0.25) {
          pieces.push([from, cut.point]);
          from = cut.point;
        }
      }
      if (dist(from, b) > 0.25) pieces.push([from, b]);
    }
  }

  const nodeIds = new Map();
  const nodes = [];
  const idOf = (p) => {
    const key = `${Math.round(p[0])},${Math.round(p[1])},${Math.round(p[2])}`;
    if (!nodeIds.has(key)) {
      nodeIds.set(key, nodes.length);
      nodes.push({ p, edges: [] });
    }
    return nodeIds.get(key);
  };
  const edges = [];
  for (const [a, b] of pieces) {
    const ia = idOf(a);
    const ib = idOf(b);
    if (ia === ib) continue;
    const edge = { a: ia, b: ib, pa: nodes[ia].p, pb: nodes[ib].p, len: dist(nodes[ia].p, nodes[ib].p) };
    edges.push(edge);
    nodes[ia].edges.push({ to: ib, len: edge.len });
    nodes[ib].edges.push({ to: ia, len: edge.len });
  }

  function snap(p) {
    let best = null;
    for (const edge of edges) {
      const hit = closestOnSegment(p, edge.pa, edge.pb);
      if (!best || hit.d < best.d) best = { edge, t: hit.t, point: hit.point, d: hit.d };
    }
    return best;
  }

  /**
   * Path over the network between two positions, as a list of points, or null
   * when either end is farther than `reach` metres from the workings.
   */
  function route(from, to, reach = 30) {
    if (!edges.length) return null;
    const s = snap(from);
    const e = snap(to);
    if (!s || !e || s.d > reach || e.d > reach) return null;
    if (s.edge === e.edge) return [from, s.point, e.point, to];
    const n = nodes.length;
    const cost = new Float64Array(n).fill(Infinity);
    const prev = new Int32Array(n).fill(-1);
    const done = new Uint8Array(n);
    cost[s.edge.a] = s.t * s.edge.len;
    cost[s.edge.b] = (1 - s.t) * s.edge.len;
    const endCost = (i) => (i === e.edge.a ? e.t * e.edge.len : i === e.edge.b ? (1 - e.t) * e.edge.len : Infinity);
    let best = Infinity;
    let bestNode = -1;
    for (;;) {
      let u = -1;
      for (let i = 0; i < n; i += 1) if (!done[i] && (u < 0 || cost[i] < cost[u])) u = i;
      if (u < 0 || cost[u] === Infinity || cost[u] >= best) break;
      done[u] = 1;
      const total = cost[u] + endCost(u);
      if (total < best) {
        best = total;
        bestNode = u;
      }
      for (const link of nodes[u].edges) {
        if (cost[u] + link.len < cost[link.to]) {
          cost[link.to] = cost[u] + link.len;
          prev[link.to] = u;
        }
      }
    }
    if (bestNode < 0) return null;
    const middle = [];
    for (let i = bestNode; i >= 0; i = prev[i]) middle.push(nodes[i].p);
    middle.reverse();
    return [from, s.point, ...middle, e.point, to];
  }

  return { route, snap, nodes: nodes.length, edges: edges.length };
}
