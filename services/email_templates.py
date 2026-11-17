"""HTML and text of the card email (contract, section 13.7).

Design approved in the wiki (*Identidad de marca* → *Correo de la tarjeta*): a
600 px white card over the muted background, the brand gradient only in the
header (same as the `/tarjeta` page), the tier's metallic finish in the card
band, one single primary blue for the action, and the business identity in text
so the message still reads with images blocked.

No `<style>` and no external CSS: everything is inline and laid out with
tables. Outlook renders with Word, which ignores `border-radius`,
`background-image` and `max-width`, so every gradient carries a solid `bgcolor`
fallback and the width goes in the table attribute.

The email never carries the card code, points, cashback or balance: the link is
the only thing of value in it.
"""

import html

FONT_BODY = "'Geist','Segoe UI',Roboto,-apple-system,Helvetica,Arial,sans-serif"
FONT_DISPLAY = "Montserrat,'Segoe UI',Roboto,-apple-system,Helvetica,Arial,sans-serif"

INK_950 = "#0a1020"
INK_600 = "#4a5870"
INK_500 = "#66758e"
MUTED = "#5a6881"
BORDER = "#dfe5ef"
BACKGROUND = "#eef2f8"
PRIMARY = "#0062f2"
PRIMARY_TEXT = "#dbebfe"
ONYX_EDGE = "#01befe"

# (gradient, solid fallback, text colour) per metallic finish, from the brand
# document. The solid colour is what Outlook shows instead of the gradient.
FINISHES: dict[str, tuple[str, str, str]] = {
    "bronze": ("linear-gradient(135deg,#f3d9c3,#cd8a52 55%,#8c5427)", "#cd8a52", "#4a2a10"),
    "silver": ("linear-gradient(135deg,#f1f4f9,#c9d1de 55%,#9aa6b8)", "#c9d1de", "#364258"),
    "gold": ("linear-gradient(135deg,#f8e7a8,#e0ae3a 55%,#a97a10)", "#e0ae3a", "#5b3d02"),
    "onyx": ("linear-gradient(135deg,#2a3550,#0a1020)", INK_950, "#eef2f8"),
}
SILVER = FINISHES["silver"]
BRAND_GRADIENT = "linear-gradient(135deg,#01befe,#0062f2 55%,#012874)"

# Never empty: an email without a tier name still has to render.
UNKNOWN_TIER = "Membresía"


def initials(name: str) -> str:
    """One or two initials of a name, as the frontend avatar does."""
    words = [word for word in name.split() if word[:1].isalnum()]
    return "".join(word[0] for word in words[:2]).upper() or "?"


def render(
    *,
    business: str,
    customer: str,
    url: str,
    tier: str,
    finish: str,
    business_logo_url: str | None,
    platform_logo_url: str,
) -> tuple[str, str]:
    """The (plain text, HTML) pair of the card email."""
    return (
        _plain(business=business, customer=customer, url=url, tier=tier),
        _html(
            business=business,
            customer=customer,
            url=url,
            tier=tier,
            finish=finish,
            business_logo_url=business_logo_url,
            platform_logo_url=platform_logo_url,
        ),
    )


def _plain(*, business: str, customer: str, url: str, tier: str) -> str:
    """The same message for readers that only take text."""
    return (
        f"Hola, {customer}:\n\n"
        f"{business} te dio una tarjeta de membresía. "
        "Ábrela para guardarla en tu teléfono.\n"
        f"Nivel: {tier or UNKNOWN_TIER}.\n\n"
        f"Ver mi tarjeta: {url}\n\n"
        "Si no esperabas este correo, puedes ignorarlo.\n"
    )


def _initials_tile(business: str) -> str:
    """What replaces the business logo when there is no public image."""
    letters = html.escape(initials(business))
    return f"""<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
<td align="center" valign="middle" width="56" height="56" style="width:56px;
  height:56px; background:{INK_950}; border-radius:14px; font-family:{FONT_BODY};
  font-size:18px; font-weight:600; color:#ffffff; letter-spacing:0.02em;">{letters}</td>
</tr></table>"""


def _business_logo(business: str, logo_url: str | None) -> str:
    """The business mark. Decorative: the name is already in the text."""
    if not logo_url:
        return _initials_tile(business)
    return (
        f'<img src="{html.escape(logo_url, quote=True)}" alt="" width="56" height="56" '
        'style="display:block; border:0; border-radius:14px; width:56px; height:56px;">'
    )


def _html(
    *,
    business: str,
    customer: str,
    url: str,
    tier: str,
    finish: str,
    business_logo_url: str | None,
    platform_logo_url: str,
) -> str:
    """The approved template. Every interpolated value is escaped."""
    place = html.escape(business)
    name = html.escape(customer)
    link = html.escape(url, quote=True)
    level = html.escape(tier or UNKNOWN_TIER)
    wordmark = html.escape(platform_logo_url, quote=True)
    gradient, solid, ink = FINISHES.get(finish, SILVER)
    edge = f" border:1px solid {ONYX_EDGE};" if finish == "onyx" else ""
    logo = _business_logo(business, business_logo_url)
    greeting = (
        f"Hola, {name}: {place} te dio una tarjeta de membresía. "
        "Ábrela para guardarla en tu teléfono."
    )

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width">
<title>Tu tarjeta de {place}</title>
</head>
<body style="margin:0; padding:0; background:{BACKGROUND};">
<div style="display:none; max-height:0; overflow:hidden; opacity:0;
  mso-hide:all;">{greeting}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
  style="background:{BACKGROUND};">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
  style="width:100%; max-width:600px; background:#ffffff; border:1px solid {BORDER};
  border-radius:16px; overflow:hidden;">
<tr><td bgcolor="{PRIMARY}" style="padding:30px 32px 34px 32px; background:{PRIMARY};
  background-image:{BRAND_GRADIENT};">
<img src="{wordmark}" alt="" height="24"
  style="display:block; border:0; height:24px; width:auto;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-top:26px;">
<tr>
<td width="56" valign="middle" style="width:56px;">{logo}</td>
<td valign="middle" style="padding-left:16px;">
<h1 style="margin:0; font-family:{FONT_DISPLAY}; font-size:24px; line-height:1.25;
  font-weight:700; letter-spacing:-0.02em; color:#ffffff;">Tu tarjeta de {place}</h1>
<p style="margin:6px 0 0 0; font-family:{FONT_BODY}; font-size:14px; line-height:20px;
  color:{PRIMARY_TEXT};">Guárdala en tu teléfono y muéstrala en caja.</p>
</td>
</tr>
</table>
</td></tr>
<tr><td style="padding:32px 32px 0 32px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
  style="width:100%; background:{solid}; background-image:{gradient};
  border-radius:20px;{edge}">
<tr><td style="padding:26px 26px 0 26px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
<tr>
<td valign="top" style="font-family:{FONT_DISPLAY}; font-size:20px; font-weight:600;
  letter-spacing:-0.01em; color:{ink};">{place}</td>
<td align="right" valign="top"><span style="display:inline-block; padding:5px 13px;
  border:1px solid {ink}; border-radius:999px; font-family:{FONT_BODY}; font-size:12px;
  font-weight:600; color:{ink};">{level}</span></td>
</tr>
</table>
</td></tr>
<tr><td height="118" style="height:118px; line-height:118px; font-size:0;">&nbsp;</td></tr>
<tr><td style="padding:0 26px 26px 26px;">
<p style="margin:0; font-family:{FONT_BODY}; font-size:13px; line-height:18px;
  color:{ink}; opacity:0.9;">Miembro</p>
<p style="margin:2px 0 0 0; font-family:{FONT_BODY}; font-size:19px; line-height:26px;
  font-weight:500; color:{ink};">{name}</p>
</td></tr>
</table>
</td></tr>
<tr><td style="padding:26px 32px 8px 32px;">
<p style="margin:0 0 22px 0; font-family:{FONT_BODY}; font-size:16px; line-height:26px;
  color:{INK_600};">{greeting}</p>
<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
<td align="center" bgcolor="{PRIMARY}" style="border-radius:12px; padding:14px 26px;">
<a href="{link}" style="display:inline-block; font-family:{FONT_BODY}; font-size:15px;
  line-height:20px; font-weight:600; color:#ffffff; text-decoration:none;">Ver mi tarjeta</a>
</td>
</tr></table>
<p style="margin:22px 0 0 0; font-family:{FONT_BODY}; font-size:13px; line-height:20px;
  color:{MUTED};">Si el botón no abre, copia este enlace:<br>
<a href="{link}" style="color:{PRIMARY}; text-decoration:underline;
  word-break:break-all;">{link}</a></p>
</td></tr>
<tr><td style="padding:24px 32px 26px 32px;">
<div style="height:1px; background:{BORDER}; line-height:1px; font-size:0;
  margin-bottom:18px;">&nbsp;</div>
<p style="margin:0 0 6px 0; font-family:{FONT_BODY}; font-size:12px; line-height:18px;
  color:{INK_600};">Si no esperabas este correo, puedes ignorarlo.</p>
<p style="margin:0; font-family:{FONT_BODY}; font-size:12px; line-height:18px;
  color:{INK_500};">{place} · Enviado con Member+</p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""
