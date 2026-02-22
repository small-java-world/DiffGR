import { UserProfile } from "./profile";

export function findByEmail(
  profiles: UserProfile[],
  email: string
): UserProfile | undefined {
  const normalizedEmail = email.trim().toLowerCase();
  return profiles.find((profile) => profile.email.toLowerCase() === normalizedEmail);
}
