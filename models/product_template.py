from odoo import models, fields, api


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # ── Champs INIES ──────────────────────────────────────────────────────────
    x_inies_ref          = fields.Char(string='Réf. INIES',                 index=True)
    x_inies_url          = fields.Char(string='Fiche INIES (URL)')
    x_inies_norme        = fields.Char(string='Norme')
    x_inies_type         = fields.Char(string='Type de déclaration')
    x_inies_verification = fields.Char(string='Vérification')
    x_inies_dvt          = fields.Integer(string='Durée de vie typique (ans)')
    x_inies_date_version = fields.Char(string='Date de version')
    x_inies_lieu_prod    = fields.Char(string='Lieu de production')
    x_inies_indicators   = fields.Html(
        string='Indicateurs environnementaux',
        sanitize=True,
        sanitize_tags=True,
        sanitize_attributes=False,
        sanitize_style=False,
        strip_style=False,
    )

    # ── Action : ouvrir le wizard de recherche ────────────────────────────────
    def action_open_inies_search(self):
        return {
            'type':    'ir.actions.act_window',
            'name':    'Recherche INIES',
            'res_model': 'inies.search.wizard',
            'view_mode': 'form',
            'target':  'new',
            'context': {
                'default_product_id': self.id,
                'default_search_value': self.name or '',
            },
        }

    # ── Action : ouvrir la fiche INIES dans le navigateur ────────────────────
    def action_open_inies_fiche(self):
        if not self.x_inies_url:
            return
        return {
            'type': 'ir.actions.act_url',
            'url':   self.x_inies_url,
            'target': 'new',
        }
