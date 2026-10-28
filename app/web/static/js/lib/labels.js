// Plain-language names for the reasons the app flags things.
export const REASON_LABELS = {
  exact_duplicate: "Exact duplicate",
  near_duplicate: "Similar to another photo",
  video_near_duplicate: "Similar to another video",
  blurry: "Blurry",
  screenshot: "Screenshot",
  document: "Document or receipt",
  whiteboard: "Whiteboard or notes",
  food: "Food",
  meme: "Meme or saved image",
  blank: "Blank or accidental",
  video: "Long video",
  screen_recording: "Screen recording",
};

export const CATEGORY_ICONS = {
  exact_duplicate: "copy",
  near_duplicate: "layers",
  video_near_duplicate: "film",
  blurry: "focus",
  screenshot: "smartphone",
  document: "file-text",
  whiteboard: "presentation",
  food: "utensils",
  meme: "sticker",
  blank: "square-dashed",
  video: "video",
  screen_recording: "monitor-play",
};

export const categoryIcon = (key) => CATEGORY_ICONS[key] ?? "image";
