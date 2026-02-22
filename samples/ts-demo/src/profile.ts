export interface UserProfile {
  id: string;
  name: string;
  email: string;
  active: boolean;
}

export function normalizeName(name: string): string {
  return name.trim().replace(/\s+/g, " ");
}

export function formatProfile(profile: UserProfile): string {
  const normalizedName = normalizeName(profile.name);
  const status = profile.active ? "active" : "inactive";
  return `${normalizedName} <${profile.email}> [${status}]`;
}
