export interface UserProfile {
  id: string;
  name: string;
  email: string;
}

export function formatProfile(profile: UserProfile): string {
  return `${profile.name} <${profile.email}>`;
}
