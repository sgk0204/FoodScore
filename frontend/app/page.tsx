import { Camera, ListChecks, ScanLine } from "lucide-react";
import Link from "next/link";

import { BandScale } from "@/components/BandScale";
import { Card } from "@/components/ui/card";

const STEPS = [
  {
    icon: Camera,
    title: "Take three photos",
    text: "The front, the nutrition table and the ingredients list.",
  },
  {
    icon: ScanLine,
    title: "We read the label",
    text: "AI transcribes the values; you can check and fix anything it misread.",
  },
  {
    icon: ListChecks,
    title: "Get a score with reasons",
    text: "A score out of 100 and exactly what lowered it — sugar, salt, additives, processing.",
  },
];

export default function Home() {
  return (
    <div className="space-y-10">
      <section className="rounded-2xl bg-brand px-6 py-10 text-white sm:px-10">
        <h1 className="text-3xl font-bold sm:text-4xl">Is this packet good for you?</h1>
        <p className="mt-3 max-w-xl text-lg text-white/90">
          Photograph a food label and get an explainable health score out of 100 in seconds.
        </p>
        <Link
          href="/scan"
          className="mt-6 inline-flex h-12 items-center rounded-lg bg-white px-6 font-semibold text-brand hover:bg-brand-light"
        >
          Scan a product
        </Link>
        <p className="mt-3 text-sm text-white/80">
          No account needed for 3 scans a day. Sign in to keep your history.
        </p>
      </section>

      <section aria-labelledby="how">
        <h2 id="how" className="mb-4 text-xl font-semibold">
          How it works
        </h2>
        <div className="grid gap-4 sm:grid-cols-3">
          {STEPS.map(({ icon: Icon, title, text }) => (
            <Card key={title}>
              <Icon aria-hidden className="mb-2 h-6 w-6 text-brand" />
              <h3 className="font-semibold">{title}</h3>
              <p className="text-sm text-gray-600">{text}</p>
            </Card>
          ))}
        </div>
      </section>

      <section aria-labelledby="bands" className="space-y-3">
        <h2 id="bands" className="text-xl font-semibold">
          What the score means
        </h2>
        <BandScale />
        <p className="text-sm text-gray-600">
          Scores combine nutrients (60%), ingredients and additives (30%) and degree of processing
          (10%), based on Nutri-Score, the UK FSA traffic-light thresholds and the NOVA
          classification.{" "}
          <Link href="/methodology" className="text-brand underline">
            See the full methodology
          </Link>
          .
        </p>
      </section>
    </div>
  );
}
