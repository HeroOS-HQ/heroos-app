import type { AuthConfig } from "@/lib/server/config";

export const WEB_ORIGIN = "https://heroos-demo.example.com";
export const COGNITO_ORIGIN = "https://heroos-demo.auth.eu-west-1.amazoncognito.com";
export const API_BASE_URL = "https://heroos-api.example.com";
export const CLIENT_ID = "abc123clientid";
export const COMPANY_ID = "d3e0a000-0000-4000-8000-000000000001";
export const SESSION_SECRET_HEX = "0f".repeat(32);

export const ENV = {
  NODE_ENV: "production",
  HEROOS_WEB_ORIGIN: WEB_ORIGIN,
  HEROOS_COGNITO_DOMAIN: COGNITO_ORIGIN,
  HEROOS_COGNITO_CLIENT_ID: CLIENT_ID,
  HEROOS_API_BASE_URL: API_BASE_URL,
  HEROOS_DEMO_COMPANY_ID: COMPANY_ID,
  HEROOS_WEB_SESSION_SECRET: SESSION_SECRET_HEX,
};

export const CONFIG: AuthConfig = {
  webOrigin: WEB_ORIGIN,
  cognitoOrigin: COGNITO_ORIGIN,
  clientId: CLIENT_ID,
  apiBaseUrl: API_BASE_URL,
  demoCompanyId: COMPANY_ID,
  sessionSecret: Buffer.from(SESSION_SECRET_HEX, "hex"),
};

/** All Set-Cookie header values of a response. */
export function setCookies(response: Response): string[] {
  return response.headers.getSetCookie();
}

/** The value of cookie `name` from a response's Set-Cookie headers. */
export function cookieValue(response: Response, name: string): string | undefined {
  const header = setCookies(response).find((cookie) => cookie.startsWith(`${name}=`));
  return header?.slice(name.length + 1).split(";")[0];
}
