import { html, useEffect, useLayoutEffect, useRef, useState } from "../lib/html.js";

const GAP = 4;

/**
 * Windowed square grid. Renders only the rows near the viewport, so scrolling a
 * 50,000-item library stays smooth. The scroll container is the nearest `.content`.
 *
 *   <VirtualGrid total=${n} minCell=${180} renderCell=${(index, size) => ...}
 *                onVisible=${(first, last) => ...} scrollToIndex=${i} />
 */
export function VirtualGrid({ total, minCell = 180, renderCell, onVisible, scrollToIndex, follow, version, header }) {
  const root = useRef(null);
  const [geometry, setGeometry] = useState({ width: 0, top: 0, scrollTop: 0, height: 0 });

  useLayoutEffect(() => {
    const scroller = root.current?.closest(".content");
    if (!scroller) return;
    const measure = () => {
      const box = root.current.getBoundingClientRect();
      const host = scroller.getBoundingClientRect();
      setGeometry({
        width: root.current.clientWidth,
        top: box.top - host.top + scroller.scrollTop,
        scrollTop: scroller.scrollTop,
        height: scroller.clientHeight,
      });
    };
    measure();
    let frame = 0;
    const onScroll = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    scroller.addEventListener("scroll", onScroll, { passive: true });
    const observer = new ResizeObserver(onScroll);
    observer.observe(scroller);
    observer.observe(root.current);
    return () => {
      scroller.removeEventListener("scroll", onScroll);
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [header]);

  const columns = Math.max(1, Math.floor((geometry.width + GAP) / (minCell + GAP)));
  const size = geometry.width ? (geometry.width - GAP * (columns - 1)) / columns : minCell;
  const rowHeight = size + GAP;
  const rows = Math.ceil((total ?? 0) / columns);
  const viewTop = geometry.scrollTop - geometry.top;
  const firstRow = Math.max(0, Math.floor(viewTop / rowHeight) - 2);
  const lastRow = Math.min(rows - 1, Math.ceil((viewTop + geometry.height) / rowHeight) + 2);
  const first = firstRow * columns;
  const last = Math.min((total ?? 0) - 1, (lastRow + 1) * columns - 1);

  useEffect(() => {
    if (total && geometry.width) onVisible?.(first, last, columns);
  }, [first, last, total, geometry.width, version]);

  useEffect(() => {
    if (scrollToIndex == null || !geometry.width) return;
    const scroller = root.current.closest(".content");
    const row = Math.floor(scrollToIndex / columns);
    scroller.scrollTo({ top: geometry.top + row * rowHeight - 8, behavior: "auto" });
  }, [scrollToIndex]);

  // Keyboard cursor: scroll only as far as needed to keep it on screen.
  useEffect(() => {
    if (follow == null || !geometry.width) return;
    const scroller = root.current.closest(".content");
    const rowTop = geometry.top + Math.floor(follow / columns) * rowHeight;
    const rowBottom = rowTop + size;
    const margin = 96; // clear of the decision tray
    if (rowTop < scroller.scrollTop + 8) scroller.scrollTop = rowTop - 8;
    else if (rowBottom > scroller.scrollTop + scroller.clientHeight - margin)
      scroller.scrollTop = rowBottom - scroller.clientHeight + margin;
  }, [follow]);

  const cells = [];
  if (geometry.width && total) {
    for (let index = first; index <= last; index++) {
      const row = Math.floor(index / columns);
      const col = index % columns;
      cells.push(html`
        <div
          key=${index}
          class="vcell"
          style=${`transform:translate(${col * (size + GAP)}px,${row * rowHeight}px);width:${size}px;height:${size}px`}
        >
          ${renderCell(index, size)}
        </div>
      `);
    }
  }

  return html`
    <div class="vgrid" ref=${root} style=${`height:${Math.max(0, rows * rowHeight - GAP)}px`} data-columns=${columns}>
      ${cells}
    </div>
  `;
}

/** Grid columns for keyboard navigation, read from the rendered grid. */
export function gridColumns(element) {
  return Number(element?.querySelector?.(".vgrid")?.dataset.columns ?? 1);
}
