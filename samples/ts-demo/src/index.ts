import { formatProfile, UserProfile } from "./profile";
import { findByEmail } from "./profiles";

const profiles: UserProfile[] = [
  {
    id: "u-001",
    name: "  Alice  ",
    email: "alice@example.com",
    active: true
  },
  {
    id: "u-002",
    name: "Bob",
    email: "bob@example.com",
    active: false
  }
];

const selected = findByEmail(profiles, "alice@example.com");
if (selected) {
  console.log(formatProfile(selected));
}
