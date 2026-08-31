/**
 * Typed browser client for every HirePro API endpoint.
 *
 * Usage:
 *   const api = new HireProApi(import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000");
 *   const { access_token } = await api.auth.login({ email, password });
 *   api.setToken(access_token);
 */

export type Id = string;
export type ISODateTime = string;

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface User {
  id: Id;
  email: string;
  full_name: string;
  is_admin: boolean;
  role: "customer" | "business";
  phone?: string | null;
  profile_image_url?: string | null;
  is_active?: boolean;
  created_at: ISODateTime;
}

export interface FAQ {
  id: Id;
  question: string;
  answer: string;
  sort_order: number;
}

export interface Category {
  id: Id;
  name: string;
  slug: string;
  description: string;
}

export interface CategoryDetail extends Category {
  faqs: FAQ[];
}

export interface Business {
  id: Id;
  owner_id: Id;
  category_id: Id;
  name: string;
  slug: string;
  description: string;
  city: string;
  address: string;
  phone: string;
  website: string;
  latitude: number | null;
  longitude: number | null;
  is_verified: boolean;
  is_active: boolean;
  view_count: number;
  created_at: ISODateTime;
}

export interface Review {
  id: Id;
  user_id: Id;
  business_id: Id;
  rating: number;
  title: string;
  comment: string;
  helpful_count: number;
  created_at: ISODateTime;
}

export interface Quote {
  id: Id;
  business_id: Id;
  details: string;
  budget: number | null;
  status: string;
  created_at: ISODateTime;
}

export interface Onboarding {
  user_id: Id;
  current_step: number;
  data: Record<string, unknown>;
  completed: boolean;
}

export interface Notification {
  id: Id;
  title: string;
  message: string;
  is_read: boolean;
  created_at: ISODateTime;
}

export interface Preference {
  email_notifications: boolean;
  push_notifications: boolean;
  theme: string;
  language: string;
}

export interface RegisterInput {
  email: string;
  password: string;
  full_name: string;
  role: "customer" | "business";
}

export interface LoginInput {
  email: string;
  password: string;
}

export interface OAuthInput {
  provider: "google" | "facebook" | "apple";
  provider_token: string;
  email: string;
  full_name: string;
}

export interface BusinessInput {
  category_id: Id;
  name: string;
  description: string;
  city: string;
  address?: string;
  phone?: string;
  website?: string;
  latitude?: number | null;
  longitude?: number | null;
}

export interface BusinessFilters {
  q?: string;
  category_id?: Id;
  city?: string;
  verified?: boolean;
  limit?: number;
  offset?: number;
}

export interface ReviewInput {
  rating: number;
  title?: string;
  comment: string;
}

export interface QuoteInput {
  business_id: Id;
  details: string;
  budget?: number | null;
}

export interface ContactInput {
  name: string;
  email: string;
  subject: string;
  message: string;
}

export interface OnboardingInput {
  current_step: number;
  data?: Record<string, unknown>;
  completed?: boolean;
}

export interface PreferenceInput {
  email_notifications?: boolean;
  push_notifications?: boolean;
  theme?: "light" | "dark" | "system";
  language?: string;
}

export interface AnalyticsInput {
  business_id?: Id | null;
  metadata?: Record<string, unknown>;
}

export interface AdminStats {
  users: number;
  businesses: number;
  reviews: number;
  quotes: number;
  open_contact_messages: number;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : `API request failed (${status})`);
    this.name = "ApiError";
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;
type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  query?: Query;
  auth?: boolean;
};

export class HireProApi {
  private token: string | null = null;
  private readonly baseUrl: string;

  constructor(origin = "http://127.0.0.1:8000") {
    this.baseUrl = `${origin.replace(/\/$/, "")}/api/v1`;
  }

  setToken(token: string | null): void {
    this.token = token;
  }

  private async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const { body, query, auth = false, headers, ...init } = options;
    const url = new URL(`${this.baseUrl}${path}`);

    Object.entries(query ?? {}).forEach(([key, value]) => {
      if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
    });

    if (auth && !this.token) throw new ApiError(401, "Authentication required");

    const response = await fetch(url, {
      ...init,
      cache: init.cache ?? "no-store",
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
        ...headers,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new ApiError(response.status, error.detail ?? error);
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }

  health = () => this.request<{ status: "ok" }>("/health");

  auth = {
    register: (input: RegisterInput) =>
      this.request<TokenResponse>("/auth/register", {
        method: "POST",
        body: input,
      }),
    login: (input: LoginInput) =>
      this.request<TokenResponse>("/auth/login", { method: "POST", body: input }),
    // Currently returns 501 until backend provider verification is configured.
    oauth: (input: OAuthInput) =>
      this.request<TokenResponse>("/auth/oauth", { method: "POST", body: input }),
    logout: () => this.request<void>("/auth/logout", { method: "POST", auth: true }),
    forgotPassword: (email: string) =>
      this.request<{ message: string }>("/auth/forgot-password", {
        method: "POST",
        body: { email },
      }),
    me: () => this.request<User>("/auth/me", { auth: true }),
  };

  categories = {
    list: () => this.request<Category[]>("/categories"),
    get: (slug: string) => this.request<CategoryDetail>(`/categories/${encodeURIComponent(slug)}`),
  };

  businesses = {
    list: (filters: BusinessFilters = {}) =>
      this.request<Business[]>("/businesses", { query: filters as Query }),
    get: (businessId: Id) =>
      this.request<Business>(`/businesses/${encodeURIComponent(businessId)}`),
    create: (input: BusinessInput) =>
      this.request<Business>("/businesses", { method: "POST", body: input, auth: true }),
    toggleFavorite: (businessId: Id) =>
      this.request<{ is_favorite: boolean }>(
        `/businesses/${encodeURIComponent(businessId)}/favorite`,
        { method: "POST", auth: true },
      ),
    share: (businessId: Id) =>
      this.request<{ url: string }>(`/businesses/${encodeURIComponent(businessId)}/share`),
    reviews: (businessId: Id) =>
      this.request<Review[]>(`/businesses/${encodeURIComponent(businessId)}/reviews`),
    submitReview: (businessId: Id, input: ReviewInput) =>
      this.request<Review>(`/businesses/${encodeURIComponent(businessId)}/reviews`, {
        method: "POST",
        body: input,
        auth: true,
      }),
  };

  reviews = {
    markHelpful: (reviewId: Id) =>
      this.request<{ helpful_count: number }>(`/reviews/${encodeURIComponent(reviewId)}/helpful`, {
        method: "POST",
        auth: true,
      }),
  };

  quotes = {
    create: (input: QuoteInput) =>
      this.request<Quote>("/quotes", { method: "POST", body: input, auth: true }),
    list: () => this.request<Quote[]>("/quotes", { auth: true }),
  };

  favorites = {
    list: () => this.request<Business[]>("/favorites", { auth: true }),
  };

  search = {
    autocomplete: (q: string) =>
      this.request<{ suggestions: string[] }>("/search/autocomplete", { query: { q } }),
    popular: () => this.request<{ searches: string[] }>("/search/popular"),
  };

  contact = {
    send: (input: ContactInput) =>
      this.request<{ id: Id; status: string }>("/contact", { method: "POST", body: input }),
    faqs: () => this.request<Array<{ question: string; answer: string }>>("/contact/faqs"),
  };

  onboarding = {
    get: () => this.request<Onboarding>("/onboarding", { auth: true }),
    update: (input: OnboardingInput) =>
      this.request<Onboarding>("/onboarding", { method: "PUT", body: input, auth: true }),
  };

  subscriptions = {
    createPro: (plan: "pro_monthly" | "pro_yearly" = "pro_monthly") =>
      this.request<{ subscription_id: Id; status: string; checkout_session_id: string }>(
        "/subscriptions/pro",
        { method: "POST", body: { plan }, auth: true },
      ),
  };

  notifications = {
    list: () => this.request<Notification[]>("/notifications", { auth: true }),
    markRead: (notificationId: Id) =>
      this.request<Notification>(`/notifications/${encodeURIComponent(notificationId)}/read`, {
        method: "PATCH",
        auth: true,
      }),
    markAllRead: () =>
      this.request<{ updated: number }>("/notifications/read-all", {
        method: "PATCH",
        auth: true,
      }),
  };

  preferences = {
    get: () => this.request<Preference>("/preferences", { auth: true }),
    update: (input: PreferenceInput) =>
      this.request<Preference>("/preferences", { method: "PUT", body: input, auth: true }),
  };

  locations = {
    cities: () => this.request<{ cities: string[] }>("/locations/cities"),
    geocode: (address: string) =>
      this.request<{ address: string; latitude: number; longitude: number }>("/locations/geocode", {
        method: "POST",
        body: { address },
      }),
    nearby: (latitude: number, longitude: number, radiusKm = 10) =>
      this.request<Business[]>("/locations/nearby", {
        query: { latitude, longitude, radius_km: radiusKm },
      }),
  };

  legal = {
    get: (slug: string) =>
      this.request<{ slug: string; title: string; content: string }>(
        `/legal/${encodeURIComponent(slug)}`,
      ),
  };

  analytics = {
    pageView: (input: AnalyticsInput = {}) => this.recordAnalytics("page-views", input),
    businessClick: (input: AnalyticsInput = {}) => this.recordAnalytics("business-clicks", input),
    quoteConversion: (input: AnalyticsInput = {}) =>
      this.recordAnalytics("quote-conversions", input),
  };

  private recordAnalytics(kind: string, input: AnalyticsInput) {
    return this.request<{ event_id: Id; status: string }>(`/analytics/${kind}`, {
      method: "POST",
      body: input,
      // Sends a bearer token when set, but these endpoints also accept anonymous requests.
    });
  }

  admin = {
    signin: (input: LoginInput) =>
      this.request<TokenResponse>("/admin/signin", { method: "POST", body: input }),
    signout: () => this.request<void>("/admin/signout", { method: "POST", auth: true }),
    users: (query: { q?: string; limit?: number; offset?: number } = {}) =>
      this.request<User[]>("/admin/users", { auth: true, query: query as Query }),
    user: (userId: Id) =>
      this.request<User>(`/admin/users/${encodeURIComponent(userId)}`, { auth: true }),
    updateUser: (userId: Id, input: Partial<User>) =>
      this.request<User>(`/admin/users/${encodeURIComponent(userId)}`, {
        method: "PATCH",
        body: input,
        auth: true,
      }),
    deleteUser: (userId: Id) =>
      this.request<void>(`/admin/users/${encodeURIComponent(userId)}`, {
        method: "DELETE",
        auth: true,
      }),
    businesses: (query: { q?: string; limit?: number; offset?: number } = {}) =>
      this.request<Business[]>("/admin/businesses", { auth: true, query: query as Query }),
    business: (businessId: Id) =>
      this.request<Business>(`/admin/businesses/${encodeURIComponent(businessId)}`, { auth: true }),
    updateBusiness: (businessId: Id, input: Partial<Business>) =>
      this.request<Business>(`/admin/businesses/${encodeURIComponent(businessId)}`, {
        method: "PATCH",
        body: input,
        auth: true,
      }),
    deleteBusiness: (businessId: Id) =>
      this.request<void>(`/admin/businesses/${encodeURIComponent(businessId)}`, {
        method: "DELETE",
        auth: true,
      }),
    verificationQueue: () =>
      this.request<Business[]>("/admin/verification", { auth: true }),
    verifyBusiness: (businessId: Id, verified: boolean) =>
      this.request<Business>(`/admin/verification/${encodeURIComponent(businessId)}`, {
        method: "PATCH",
        body: { verified },
        auth: true,
      }),
    stats: () => this.request<AdminStats>("/admin/stats", { auth: true }),
    reviewQueue: () =>
      this.request<Review[]>("/admin/moderation/reviews", { auth: true }),
    moderateReview: (reviewId: Id, approved: boolean) =>
      this.request<Review>(`/admin/moderation/reviews/${encodeURIComponent(reviewId)}`, {
        method: "PATCH",
        body: { approved },
        auth: true,
      }),
  };
}

export const hireProApi = new HireProApi(
  // Vite example: pass import.meta.env.VITE_API_URL here in your app bootstrap.
  "http://127.0.0.1:8000",
);
