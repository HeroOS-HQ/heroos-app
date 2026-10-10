import { type NextRequest, NextResponse } from "next/server";

import { cognitoOriginFrom, contentSecurityPolicy } from "@/lib/csp";

/**
 * Per-request CSP nonce. Next.js reads the nonce from the request's
 * Content-Security-Policy header and applies it to its scripts; the root layout
 * renders dynamically so every page gets a fresh one (docs/architecture/authentication.md §10).
 */
export function proxy(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const policy = contentSecurityPolicy({
    nonce,
    cognitoOrigin: cognitoOriginFrom(process.env.HEROOS_COGNITO_DOMAIN),
    development: process.env.NODE_ENV === "development",
  });

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", policy);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", policy);
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
