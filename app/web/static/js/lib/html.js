// One import for everything a component needs: the html tagged template, hooks, signals.
import { h, render, Fragment } from "preact";
import htm from "htm";

export const html = htm.bind(h);
export { h, render, Fragment };
export {
  useState, useEffect, useLayoutEffect, useRef, useMemo, useCallback, useReducer,
} from "preact/hooks";
export { signal, computed, effect, batch } from "@preact/signals";
