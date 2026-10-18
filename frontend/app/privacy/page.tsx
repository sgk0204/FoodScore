import { DeleteAccount } from "@/components/DeleteAccount";

export const metadata = { title: "Privacy" };

export default function PrivacyPage() {
  return (
    <article className="prose max-w-none space-y-4 text-gray-800">
      <h1 className="text-2xl font-bold">Privacy</h1>
      <p>
        FoodScore is designed to collect as little as possible (India Digital Personal Data
        Protection Act, 2023).
      </p>
      <ul className="list-disc space-y-1 pl-5">
        <li>
          <strong>Photos</strong> are resized and stripped of metadata (including GPS) on your
          device, re-encoded again on our server, used only to read the label, and deleted as soon
          as the label is read — always within 24 hours.
        </li>
        <li>
          <strong>Account data</strong> is your email and a hashed password. We never store your
          password itself.
        </li>
        <li>
          <strong>Scan results</strong> (extracted values and scores) are kept in your history until
          you delete them.
        </li>
        <li>Logs never contain passwords, tokens or images; user ids in logs are hashed.</li>
        <li>No ads, no tracking, no selling of data.</li>
      </ul>
      <h2 className="text-xl font-semibold">Delete your data</h2>
      <p>
        Deleting your account permanently removes your account, scans, corrections and feedback.
      </p>
      <DeleteAccount />
    </article>
  );
}
