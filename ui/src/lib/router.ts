import { useEffect, useState } from "react";

/** Hash-Routen, damit das statische Frontend ohne Server-Fallback auskommt. */
export type Route =
  | { screen: "start" }
  | { screen: "analyse"; jobId: string }
  | { screen: "review"; hash: string }
  | { screen: "export"; hash: string }
  | { screen: "settings" };

export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  switch (parts[0]) {
    case "analyse":
      return parts[1] ? { screen: "analyse", jobId: parts[1] } : { screen: "start" };
    case "review":
      return parts[1] ? { screen: "review", hash: parts[1] } : { screen: "start" };
    case "export":
      return parts[1] ? { screen: "export", hash: parts[1] } : { screen: "start" };
    case "settings":
      return { screen: "settings" };
    default:
      return { screen: "start" };
  }
}

export function href(route: Route): string {
  switch (route.screen) {
    case "start":
      return "#/";
    case "analyse":
      return `#/analyse/${route.jobId}`;
    case "review":
      return `#/review/${route.hash}`;
    case "export":
      return `#/export/${route.hash}`;
    case "settings":
      return "#/settings";
  }
}

export function navigate(route: Route): void {
  window.location.hash = href(route);
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash));
  useEffect(() => {
    const on = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}
