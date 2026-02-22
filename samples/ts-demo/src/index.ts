import { formatProfile, UserProfile } from "./profile";

const profile: UserProfile = {
  id: "u-001",
  name: "Alice",
  email: "alice@example.com"
};

console.log(formatProfile(profile));
