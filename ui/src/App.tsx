import { Shell } from "./components/Shell";
import { useRoute } from "./lib/router";
import { Analyse } from "./screens/Analyse";
import { Export } from "./screens/Export";
import { Review } from "./screens/Review";
import { Settings } from "./screens/Settings";
import { Start } from "./screens/Start";

export function App() {
  const route = useRoute();
  let screen: React.ReactNode;
  switch (route.screen) {
    case "analyse":
      screen = <Analyse jobId={route.jobId} />;
      break;
    case "review":
      screen = <Review hash={route.hash} key={route.hash} />;
      break;
    case "export":
      screen = <Export hash={route.hash} />;
      break;
    case "settings":
      screen = <Settings />;
      break;
    default:
      screen = <Start />;
  }
  return <Shell route={route}>{screen}</Shell>;
}
