import dynamic from "next/dynamic";

const USRealView = dynamic(() => import("../components/USRealView"), {
  ssr: false,
});

export default function HomePage() {
  return <USRealView />;
}
