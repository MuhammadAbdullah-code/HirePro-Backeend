/** HirePro dashboard API client. Contains only endpoints from the approved dashboard specification. */
export type Json = Record<string, unknown>;
export type Role = "customer" | "business";
export interface AuthTokens { access_token: string; refresh_token: string | null; token_type: "bearer" }

export class DashboardApi {
  private accessToken: string | null = null;
  constructor(private readonly baseUrl = "http://127.0.0.1:8000/api/v1") {}
  setToken(token: string | null) { this.accessToken = token; }
  private async call<T>(path: string, method = "GET", body?: unknown, query?: Json): Promise<T> {
    const url = new URL(`${this.baseUrl}${path}`);
    Object.entries(query ?? {}).forEach(([k, v]) => v != null && url.searchParams.set(k, String(v)));
    const response = await fetch(url, { method, headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(this.accessToken ? { Authorization: `Bearer ${this.accessToken}` } : {}),
    }, body: body === undefined ? undefined : JSON.stringify(body) });
    if (!response.ok) throw Object.assign(new Error((await response.json().catch(() => ({}))).detail ?? "API error"), { status: response.status });
    return response.status === 204 ? undefined as T : response.json();
  }
  auth = {
    register: (body: {full_name:string; email:string; password:string; role:Role}) => this.call<AuthTokens>("/auth/register", "POST", body),
    login: (body: {email:string; password:string}) => this.call<AuthTokens>("/auth/login", "POST", body),
    me: () => this.call<Json>("/auth/me"), logout: () => this.call<void>("/auth/logout", "POST"),
    forgotPassword: (email:string) => this.call<Json>("/auth/forgot-password", "POST", {email}),
    resetPassword: (token:string, new_password:string) => this.call<void>("/auth/reset-password", "POST", {token,new_password}),
    refresh: (refresh_token:string) => this.call<AuthTokens>("/auth/refresh", "POST", {refresh_token}),
  };
  discovery = {
    businesses: (filters:Json={}) => this.call<Json[]>("/businesses", "GET", undefined, filters),
    business: (id:string) => this.call<Json>(`/businesses/${id}`), reviews: (id:string) => this.call<Json[]>(`/businesses/${id}/reviews`),
    categories: () => this.call<Json[]>("/categories"), category: (slug:string) => this.call<Json>(`/categories/${slug}`),
    cities: () => this.call<Json>("/locations/cities"), nearby: (query:Json) => this.call<Json[]>("/locations/nearby", "GET", undefined, query),
    autocomplete: (q:string) => this.call<Json>("/search/autocomplete", "GET", undefined, {q}), popular: () => this.call<Json>("/search/popular"),
  };
  customer = {
    dashboard: () => this.call<Json>("/customer/dashboard"), requests: (query:Json={}) => this.call<Json[]>("/customer/requests", "GET", undefined, query),
    createRequest: (body:Json) => this.call<Json>("/customer/requests", "POST", body), request: (id:string) => this.call<Json>(`/customer/requests/${id}`),
    updateRequest: (id:string, body:Json) => this.call<Json>(`/customer/requests/${id}`, "PATCH", body), deleteRequest: (id:string) => this.call<void>(`/customer/requests/${id}`, "DELETE"),
    requestAction: (id:string, action:"cancel"|"close"|"extend") => this.call<Json>(`/customer/requests/${id}/${action}`, "POST"),
    quotes: (requestId:string) => this.call<Json[]>(`/customer/requests/${requestId}/quotes`), quote: (id:string) => this.call<Json>(`/customer/quotes/${id}`),
    quoteAction: (id:string, action:"accept"|"decline") => this.call<Json>(`/customer/quotes/${id}/${action}`, "POST"),
    messages: (id:string) => this.call<Json[]>(`/customer/quotes/${id}/messages`), sendMessage: (id:string, body:string) => this.call<Json>(`/customer/quotes/${id}/messages`, "POST", {body}),
    readMessages: (id:string) => this.call<Json>(`/customer/quotes/${id}/messages/read`, "POST"), favorites: () => this.call<Json[]>("/customer/favorites"),
    save: (id:string) => this.call<Json>(`/customer/favorites/${id}`, "POST"), unsave: (id:string) => this.call<void>(`/customer/favorites/${id}`, "DELETE"),
    compare: (business_ids:string[]) => this.call<Json[]>("/customer/favorites/compare", "POST", {business_ids}),
    notifications: (query:Json={}) => this.call<Json[]>("/customer/notifications", "GET", undefined, query), unread: () => this.call<Json>("/customer/notifications/unread-count"),
    readNotification: (id:string) => this.call<Json>(`/customer/notifications/${id}/read`, "PATCH"), readAll: () => this.call<Json>("/customer/notifications/read-all", "PATCH"),
    profile: () => this.call<Json>("/customer/profile"), updateProfile: (body:Json) => this.call<Json>("/customer/profile", "PATCH", body),
    preferences: () => this.call<Json>("/customer/preferences"), updatePreferences: (body:Json) => this.call<Json>("/customer/preferences", "PATCH", body),
  };
  provider = {
    dashboard: () => this.call<Json>("/provider/dashboard"), requests: (query:Json={}) => this.call<Json[]>("/provider/requests", "GET", undefined, query),
    request: (id:string) => this.call<Json>(`/provider/requests/${id}`), respond: (id:string, body:Json) => this.call<Json>(`/provider/requests/${id}/respond`, "POST", body),
    decline: (id:string) => this.call<void>(`/provider/requests/${id}/decline`, "POST"), quotes: (query:Json={}) => this.call<Json[]>("/provider/quotes", "GET", undefined, query),
    createQuote: (body:Json) => this.call<Json>("/provider/quotes", "POST", body), quote: (id:string) => this.call<Json>(`/provider/quotes/${id}`),
    updateQuote: (id:string, body:Json) => this.call<Json>(`/provider/quotes/${id}`, "PATCH", body), withdraw: (id:string) => this.call<Json>(`/provider/quotes/${id}/withdraw`, "POST"),
    business: () => this.call<Json>("/provider/business"), createBusiness: (body:Json) => this.call<Json>("/provider/business", "POST", body), updateBusiness: (body:Json) => this.call<Json>("/provider/business", "PATCH", body),
    resource: (name:string) => this.call<Json[]>(`/provider/business/${name}`), createResource: (name:string, body:Json) => this.call<Json>(`/provider/business/${name}`, "POST", body),
    verification: () => this.call<Json>("/provider/verification"), submitVerification: (body:Json={}) => this.call<Json>("/provider/verification", "POST", body),
    insight: (metric:string, query:Json={}) => this.call<Json>(`/provider/insights/${metric}`, "GET", undefined, query), subscription: () => this.call<Json>("/provider/subscription"),
  };
  admin = {
    signin: (body:{email:string;password:string}) => this.call<AuthTokens>("/admin/signin", "POST", body), signout: () => this.call<void>("/admin/signout", "POST"), me: () => this.call<Json>("/admin/me"),
    dashboard: () => this.call<Json>("/admin/dashboard"), stats: () => this.call<Json>("/admin/stats"), activity: () => this.call<Json[]>("/admin/activity"), queue: () => this.call<Json>("/admin/action-queue"),
    list: (resource:string, query:Json={}) => this.call<Json[]>(`/admin/${resource}`, "GET", undefined, query), get: (resource:string,id:string) => this.call<Json>(`/admin/${resource}/${id}`),
    update: (resource:string,id:string,body:Json) => this.call<Json>(`/admin/${resource}/${id}`, "PATCH", body), remove: (resource:string,id:string) => this.call<void>(`/admin/${resource}/${id}`, "DELETE"),
    action: (resource:string,id:string,action:string,body:Json={}) => this.call<Json>(`/admin/${resource}/${id}/${action}`, "POST", body),
    analytics: (metric:string, query:Json={}) => this.call<Json>(`/admin/analytics/${metric}`, "GET", undefined, query), settings: () => this.call<Json>("/admin/settings"), updateSettings: (body:Json) => this.call<Json>("/admin/settings", "PATCH", body),
  };
  supporting = { health: () => this.call<Json>("/health"), contact: (body:Json) => this.call<Json>("/contact", "POST", body), faqs: () => this.call<Json[]>("/contact/faqs"), legal: (slug:string) => this.call<Json>(`/legal/${slug}`) };
}

export const dashboardApi = new DashboardApi();
