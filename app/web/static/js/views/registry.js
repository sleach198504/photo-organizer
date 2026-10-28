// Maps the first segment of the route to its view.
import { HomeView } from "./home.js";
import { ScanView } from "./scan.js";
import { SettingsView } from "./settings.js";
import { ReviewView } from "./review.js";
import { RemovedView } from "./removed.js";
import { PhotosView } from "./library.js";
import { VideosView } from "./videos.js";
import { TripsView } from "./trips.js";
import { SearchView } from "./search.js";
import { OrganizeView } from "./organize.js";

const VIEWS = {
  "": HomeView,
  photos: PhotosView,
  videos: VideosView,
  trips: TripsView,
  review: ReviewView,
  removed: RemovedView,
  organize: OrganizeView,
  search: SearchView,
  scan: ScanView,
  settings: SettingsView,
};

export function routeView(route) {
  return VIEWS[route.parts[0] ?? ""] ?? HomeView;
}
