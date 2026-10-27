import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { PropsWithChildren } from 'react'

import { translateDynamicZhCN, zhCN } from './messages'
import type { MessageKey, MessageParams } from './messages'

export type Locale = 'zh' | 'en'

type I18nContextValue = {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: MessageKey, params?: MessageParams) => string
  tx: (message: string, params?: MessageParams) => string
}

export type Translate = I18nContextValue['t']

const LOCALE_STORAGE_KEY = 'nasus.locale'
const DEFAULT_LOCALE: Locale = 'zh'

const I18nContext = createContext<I18nContextValue | null>(null)

function readInitialLocale(): Locale {
  if (typeof window === 'undefined') return DEFAULT_LOCALE
  const persisted = window.localStorage.getItem(LOCALE_STORAGE_KEY)
  return persisted === 'en' || persisted === 'zh' ? persisted : DEFAULT_LOCALE
}

function interpolate(message: string, params?: MessageParams): string {
  if (!params) return message
  return message.replace(/\{(\w+)\}/g, (placeholder, name: string) => {
    const value = params[name]
    return value === undefined ? placeholder : String(value)
  })
}

export function I18nProvider({ children }: PropsWithChildren) {
  const [locale, setLocaleState] = useState<Locale>(readInitialLocale)

  useEffect(() => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale)
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en'
  }, [locale])

  const setLocale = useCallback((nextLocale: Locale) => {
    setLocaleState(nextLocale)
  }, [])

  const tx = useCallback((source: string, params?: MessageParams): string => {
    const normalizedKey = source.toLowerCase().replaceAll('_', ' ')
    const message = locale === 'zh'
      ? zhCN[source as MessageKey] ?? zhCN[normalizedKey as MessageKey] ?? translateDynamicZhCN(source) ?? source
      : source
    return interpolate(message, params)
  }, [locale])

  const t = useCallback((key: MessageKey, params?: MessageParams): string => {
    return tx(key, params)
  }, [tx])

  const contextValue = useMemo(
    () => ({ locale, setLocale, t, tx }),
    [locale, setLocale, t, tx],
  )

  return <I18nContext.Provider value={contextValue}>{children}</I18nContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components -- the hook is the provider's public context API.
export function useI18n(): I18nContextValue {
  const context = useContext(I18nContext)
  if (!context) throw new Error('useI18n must be used within I18nProvider')
  return context
}
