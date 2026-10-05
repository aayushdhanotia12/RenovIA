// Typed wrappers around the backend API. The browser never computes a price:
// every figure shown comes from a quote the server returned.

export type MoneyJ = { minor: number; currency: string };
export type Point = [number, number];

export type Finish = {
  id: string; line: "estilo" | "diseno" | "basik"; name: string; code: string | null;
  category: string; category_inferred: boolean; swatch_url: string; tags: string[]; available?: boolean;
};
export type Profile = { id: string; name: string; display: string; finish_lines: string[] };
export type StyleId = "minimalista" | "calido" | "contraste" | "creativo";
export type Style = { id: StyleId; name: { es: string; en: string }; blurb: { es: string; en: string } };
export type Catalogue = { finishes: Finish[]; profiles: Profile[]; currency: string; price_list_status: string;
  styles: Style[]; placeholder_swatches?: boolean };

export type CountertopRun = { run_id: string; length_mm: number; depth_mm: number };
export type SplashRun = { run_id: string; length_mm: number; height_mm: number };
export type Measurements = { countertop_runs: CountertopRun[]; splash_runs: SplashRun[]; sinks: number; confirmed_questions?: string[] };
export type Question = { id: string; field: string; message: string };

export type Photo = { id: string; width: number; height: number; url?: string; path: string;
  checks: { light: string; sharp: string; camera_info: string;
            camera?: { focal_px: number; focal_35mm: number; source: "exif" | "default"; lens: string } } | null };
export type SurfaceItem = { surface_id: string; surface_class: "countertop" | "backsplash"; run_id: string;
  quad: Point[]; polygon?: Point[] | null; mask_file?: string | null; score?: number | null };
export type Suggestion = { title: string; countertop_finish_id: string; profile_id: string;
  backsplash_finish_id: string | null; reason: string };
export type BoardItem = { style_id: StyleId; design_id?: string; title?: string; reason?: string;
  countertop_finish_id?: string; splash_finish_id?: string | null; profile_id?: string; image_url?: string;
  estimate?: { low: MoneyJ; high: MoneyJ }; error?: string };
export type Project = { id: string; measurements: (Measurements & { scale_confidence: string }) | null;
  photos: Photo[]; surfaces: Record<string, { confirmed: boolean; items: SurfaceItem[] }> | null;
  suggestions: { items: Suggestion[]; style: string; style_id?: StyleId | null } | null;
  style_board: { photo_id: string; budget: string | null; items: BoardItem[] } | null;
  designs: { id: string; photo_id: string }[] };

export type QuoteLine = { group: "materials" | "labour"; kind: string; surface: string | null; description: string;
  qty: number; unit: string; unit_price: MoneyJ; total: MoneyJ; detail: string; finish_id: string | null };
export type Quote = { currency: string; lines: QuoteLine[]; materials: MoneyJ; labour: MoneyJ; subtotal: MoneyJ;
  tax: MoneyJ; tax_rate_bp: number; total: MoneyJ; estimate: { low: MoneyJ; high: MoneyJ }; booking_fee: MoneyJ;
  balance: { low: MoneyJ; high: MoneyJ }; scale_confidence: string; estimate_only: boolean;
  price_list_status: string; assumptions: string[] };
export type Layer = { surface_id: string; surface_class: string; run_id: string; finish_id: string; finish_name: string;
  polygon: Point[]; centroid: Point; area_mm2: number; confidence: number; mask_url?: string };
export type Design = { id: string; project_id: string; photo_id: string; created_at?: number;
  choice: { countertop_finish_id: string; profile_id: string; splash_finish_id: string | null; fulfilment_type: string };
  manifest: { render_id: string; image: { url: string; width: number; height: number }; before_url: string; layers: Layer[] };
  quote: Quote; finishes: { countertop: Finish; backsplash: Finish | null }; profile: Profile; model_versions: Record<string, string> };
// A design opened from a share link: no project, nothing personal.
export type SharedDesign = Omit<Design, "project_id" | "photo_id" | "model_versions"> & { shared: true };
export type JobEvent = { seq: number; stage: string; status: string; detail: string | null; percent: number | null; result?: any };

export type BookingStatus = "new" | "scheduled" | "visited" | "cancelled";
export type StaffBooking = { id: string; project_id: string; design_id: string | null; created_at: number;
  updated_at: number | null; status: BookingStatus; name: string; phone: string; address: string;
  preferred_window: string | null; fulfilment_type: "SELF" | "MANAGED"; notes: string | null;
  scheduled_at: string | null; assigned_to: string | null; staff_notes: string | null; visited_at: number | null;
  whatsapp: string | null; estimate: { low: MoneyJ; high: MoneyJ } | null; final_total: MoneyJ | null;
  countertop: Finish | null; backsplash: Finish | null; profile: string | null; thumb_url: string | null };
export type RunDiff = { run_id: string; team_mm: number; customer_mm: number | null; diff_mm?: number; diff_bp?: number };
export type Verified = { countertop_runs: CountertopRun[]; splash_runs: SplashRun[]; sinks: number; tool: string;
  measured_by: string | null; notes: string | null; at: number;
  differences: { countertop: RunDiff[]; backsplash: RunDiff[] }; within_range: boolean; vs_estimate_minor: number };
export type StaffDetail = { booking: StaffBooking; verified: Verified | null; final_quote: Quote | null;
  design: Omit<Design, "project_id" | "photo_id"> | null; measurements: (Measurements & { scale_confidence: string }) | null };
export type PriceInfo = { status: string; version: string; file: string; source: string | null;
  imported_at: string | null; owner: string | null; currency: string };

async function call<T>(method: string, url: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: { ...headers } };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const r = await fetch(url, init);
  const text = await r.text();
  const data = text ? JSON.parse(text) : null;
  if (!r.ok) {
    const detail = data?.detail;
    const message = typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail.map((d: any) => typeof d === "string" ? d : `${(d.loc || []).join(".")}: ${d.msg}`).join("; ")
      : `HTTP ${r.status}`;
    const err = new Error(message) as Error & { status?: number; lines?: string[] };
    err.status = r.status;
    if (Array.isArray(detail) && detail.every((d: any) => typeof d === "string")) err.lines = detail;
    throw err;
  }
  return data as T;
}

const staff = (token: string) => ({ "X-Staff-Token": token });

export const api = {
  catalogue: () => call<Catalogue>("GET", "/api/catalogue"),
  createProject: () => call<Project>("POST", "/api/projects"),
  project: (pid: string) => call<Project>("GET", `/api/projects/${pid}`),
  putMeasurements: (pid: string, m: Measurements) =>
    call<{ questions: Question[] }>("PUT", `/api/projects/${pid}/measurements`, m),
  uploadPhoto: (pid: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return call<Photo>("POST", `/api/projects/${pid}/photos`, fd);
  },
  analyse: (pid: string, photo_id: string, language: string) =>
    call<{ job_id: string }>("POST", `/api/projects/${pid}/analyse`, { photo_id, language }),
  putSurfaces: (pid: string, photo_id: string, items: SurfaceItem[]) =>
    call("PUT", `/api/projects/${pid}/surfaces`, { photo_id, items }),
  suggest: (pid: string, style: string, style_id: StyleId | null, budget: string | null, language: string) =>
    call<{ job_id: string }>("POST", `/api/projects/${pid}/suggest`, { style, style_id, budget, language }),
  styleBoard: (pid: string, photo_id: string, budget: string | null, language: string) =>
    call<{ job_id: string }>("POST", `/api/projects/${pid}/styles`, { photo_id, budget, language }),
  design: (pid: string, body: { photo_id: string; countertop_finish_id: string; profile_id: string;
    splash_finish_id: string | null; fulfilment_type: string; language: string }) =>
    call<{ job_id: string }>("POST", `/api/projects/${pid}/designs`, body),
  getDesign: (did: string) => call<Design>("GET", `/api/designs/${did}`),
  shareDesign: (did: string) => call<{ share_id: string; url: string }>("POST", `/api/designs/${did}/share`),
  shared: (sid: string) => call<SharedDesign>("GET", `/api/shared/${sid}`),
  job: (jid: string) => call<{ status: string; result: any; error: string | null; events: JobEvent[] }>("GET", `/api/jobs/${jid}`),
  book: (pid: string, body: Record<string, unknown>) => call<{ id: string }>("POST", `/api/projects/${pid}/bookings`, body),

  staffBookings: (token: string) =>
    call<{ bookings: StaffBooking[]; prices: PriceInfo }>("GET", "/api/staff/bookings", undefined, staff(token)),
  staffBooking: (token: string, bid: string) =>
    call<StaffDetail>("GET", `/api/staff/bookings/${bid}`, undefined, staff(token)),
  staffUpdate: (token: string, bid: string, body: Partial<Pick<StaffBooking, "status" | "scheduled_at" | "assigned_to" | "staff_notes">>) =>
    call<StaffDetail>("PATCH", `/api/staff/bookings/${bid}`, body, staff(token)),
  staffVisit: (token: string, bid: string, body: { countertop_runs: CountertopRun[]; splash_runs: SplashRun[];
    sinks: number; tool: string; measured_by: string | null; notes: string | null; language: string }) =>
    call<StaffDetail>("POST", `/api/staff/bookings/${bid}/visit`, body, staff(token)),
  staffPrices: (token: string) =>
    call<{ prices: PriceInfo; sheet_url: string | null }>("GET", "/api/staff/prices", undefined, staff(token)),
  staffImportPrices: (token: string, url: string) =>
    call<{ prices: PriceInfo; warnings: string[] }>("POST", "/api/staff/prices/import", { url }, staff(token)),
};

// Follow a job's progress: Server-Sent Events first (EventSource resumes with
// Last-Event-ID on its own), polling every 3 s if the stream cannot open.
export function followJob(jid: string, onEvent: (e: JobEvent) => void): () => void {
  let closed = false;
  let lastSeq = 0;
  let pollTimer: number | undefined;
  const deliver = (e: JobEvent) => {
    if (e.seq <= lastSeq) return;
    lastSeq = e.seq;
    onEvent(e);
  };
  const poll = async () => {
    if (closed) return;
    try {
      const job = await api.job(jid);
      job.events.forEach(deliver);
      if (job.status === "done" || job.status === "failed") {
        if (!job.events.some((e) => e.stage === "JOB"))
          deliver({ seq: lastSeq + 1, stage: "JOB", status: job.status, detail: job.error, percent: null, result: job.result });
        return;
      }
    } catch { /* keep trying */ }
    pollTimer = window.setTimeout(poll, 3000);
  };
  let failures = 0;
  const es = new EventSource(`/api/jobs/${jid}/events`);
  es.addEventListener("progress", (msg) => {
    const e = JSON.parse((msg as MessageEvent).data) as JobEvent;
    deliver(e);
    if (e.stage === "JOB") es.close();
  });
  es.onerror = () => {
    failures += 1;
    if (failures >= 3) { es.close(); poll(); }
  };
  return () => { closed = true; es.close(); if (pollTimer) window.clearTimeout(pollTimer); };
}
