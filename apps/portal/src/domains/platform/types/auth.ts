export interface UserProfile {
  id: string
  name: string
  email: string
  role: string
  avatar_url?: string | null
  avatar_preset?: string | null
  avatar_image?: boolean
  avatar_updated_at?: string | null
}

export interface AuthSession {
  access_token: string
  token_type: 'Bearer'
  expires_at: string
  user: UserProfile
}

export interface AuthRegisterPayload {
  email: string
  password: string
  name?: string
}

export interface AuthLoginPayload {
  email: string
  password: string
}
