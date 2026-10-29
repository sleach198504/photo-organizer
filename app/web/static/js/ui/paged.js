import { useCallback, useEffect, useRef, useState } from "../lib/html.js";

/**
 * Sparse, page-at-a-time list for huge libraries. Only the pages the viewport
 * asks for are fetched, so a 50,000-photo library costs the same to open as 50.
 *
 *   const list = usePagedList((offset, limit) => api.get(...), { deps: [filters] })
 *   list.total, list.get(index) (undefined until loaded), list.ensure(index)
 */
export function usePagedList(fetchPage, { pageSize = 200, deps = [] } = {}) {
  const pages = useRef(new Map());
  const inflight = useRef(new Set());
  const generation = useRef(0);
  const fetchRef = useRef(fetchPage);
  fetchRef.current = fetchPage;
  const [state, setState] = useState({ total: null, tick: 0, error: null });

  const load = useCallback(
    async (page) => {
      if (pages.current.has(page) || inflight.current.has(page)) return;
      inflight.current.add(page);
      const mine = generation.current;
      try {
        const result = await fetchRef.current(page * pageSize, pageSize);
        if (mine !== generation.current) return;
        pages.current.set(page, result.items);
        setState((s) => ({ total: result.total, tick: s.tick + 1, error: null }));
      } catch (error) {
        if (mine === generation.current) setState((s) => ({ ...s, error: error.message }));
      } finally {
        inflight.current.delete(page);
      }
    },
    [pageSize]
  );

  useEffect(() => {
    generation.current += 1;
    pages.current = new Map();
    inflight.current = new Set();
    setState({ total: null, tick: 0, error: null });
    load(0);
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps

  const get = useCallback(
    (index) => pages.current.get(Math.floor(index / pageSize))?.[index % pageSize],
    [pageSize]
  );
  const ensure = useCallback((index) => load(Math.floor(index / pageSize)), [load, pageSize]);

  const reload = useCallback(() => {
    generation.current += 1;
    pages.current = new Map();
    inflight.current = new Set();
    load(0);
  }, [load]);

  /** Every item loaded so far, in order (for things like lightbox navigation). */
  const loaded = useCallback(() => {
    const out = [];
    for (const key of [...pages.current.keys()].sort((a, b) => a - b)) out.push(...pages.current.get(key));
    return out;
  }, []);

  return { total: state.total, error: state.error, tick: state.tick, get, ensure, reload, loaded };
}
