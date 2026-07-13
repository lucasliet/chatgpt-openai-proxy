export interface Credentials {
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
  accountId: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token?: string;
  expires_in: number;
  id_token?: string;
  token_type: string;
}

export type CredentialsSource = "env" | "file";
