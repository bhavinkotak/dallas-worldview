import dynamic from "next/dynamic";

const DallasWorldView = dynamic(() => import("../components/DallasWorldView"), {
  ssr: false,
});

export default function HomePage() {
  return <DallasWorldView />;
}
