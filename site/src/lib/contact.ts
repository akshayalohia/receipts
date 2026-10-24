// Support address shown on the site. Set PUBLIC_CONTACT_EMAIL in Vercel (build-time).
export const CONTACT_EMAIL: string = (import.meta.env.PUBLIC_CONTACT_EMAIL as string | undefined) || '';
export const CONTACT_TEXT: string = CONTACT_EMAIL || 'the support link on your Whop receipt';
