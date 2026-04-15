import base64
import http.cookiejar
import json
import logging
import urllib.parse
import urllib.request
import ssl

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

BASE_URL = "https://base-inies.fr"

PRODUIT_TYPES = {1: "FDES (Individuelle)", 2: "FDES (Collective)",
                 3: "DED", 4: "PEP"}
STATUTS       = {1: "En cours", 2: "En attente", 3: "En ligne",
                 4: "Archivé", 5: "Refusé"}
VERIFICATIONS = {0: "Non vérifié", 1: "Auto-déclaré",
                 2: "Vérifié (interne)", 3: "Vérifié (accrédité)",
                 4: "Vérifié tierce partie"}

DOC_TYPES = {1: "FDES", 2: "DED", 3: "Attestation", 4: "Rapport", 5: "Documentation", 6: "Image"}


def _api_get(path):
    """Appel GET vers l'API INIES."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Odoo-INIES-Connector/1.0",
        "Accept":     "application/json",
    })
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return json.loads(r.read().decode())


def _api_post(path, payload):
    """Appel POST vers l'API INIES."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        f"{BASE_URL}{path}", data=data,
        headers={
            "User-Agent":   "Odoo-INIES-Connector/1.0",
            "Accept":       "application/json",
            "Content-Type": "application/json",
            "Origin":       BASE_URL,
            "Referer":      f"{BASE_URL}/consultation/recherche",
        })
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return json.loads(r.read().decode())


class InesSearchResult(models.TransientModel):
    _name        = 'inies.search.result'
    _description = 'Résultat de recherche INIES'

    wizard_id        = fields.Many2one('inies.search.wizard', ondelete='cascade')
    inies_id         = fields.Integer(string='ID INIES')
    nom              = fields.Char(string='Nom du produit')
    ref              = fields.Char(string='Référence')
    type_declaration = fields.Char(string='Type')
    statut           = fields.Char(string='Statut')
    norme            = fields.Char(string='Norme')
    data_json        = fields.Text(string='Données brutes')

    def action_import(self):
        """Importe ce résultat dans le produit du wizard."""
        self.ensure_one()
        wizard = self.wizard_id
        if not wizard.product_id:
            raise UserError("Aucun produit cible sélectionné.")

        # Charger les données complètes depuis l'API INIES
        try:
            units  = {u['idUnite']: u['nomUnite']
                      for u in _api_get("/api/Unite")}
            normes = {n['idNorme']: n.get('nomNorme', n.get('nom', ''))
                      for n in _api_get("/api/Norme")}
            product_data = _api_get(f"/api/Produit/{self.inies_id}")
        except Exception as e:
            raise UserError(f"Erreur lors du chargement des données INIES : {e}")

        self._populate_product(wizard.product_id, product_data, units, normes)

        # Confirmer et fermer le wizard
        return {
            'type':   'ir.actions.client',
            'tag':    'display_notification',
            'params': {
                'title':   'Import INIES réussi',
                'message': f"Le produit « {self.nom} » a été mis à jour.",
                'type':    'success',
                'sticky':  False,
                'next':    {'type': 'ir.actions.act_window_close'},
            },
        }

    def _populate_product(self, product, data, units, normes):
        """Remplit les champs du produit Odoo avec les données INIES."""
        def fmt_date(d):
            if not d:
                return ''
            try:
                from datetime import datetime
                return datetime.fromisoformat(d.rstrip('Z').split('.')[0]).strftime('%d/%m/%Y')
            except Exception:
                return d or ''

        pd_list = data.get('tProduitData', [])
        pd      = pd_list[0] if pd_list else {}

        # UoM
        id_unit = data.get('idUnitUf')
        unite   = units.get(id_unit, '') if id_unit else ''
        uom_rec = self.env['uom.uom'].search([('name', '=', unite)], limit=1)
        if not uom_rec and unite:
            uom_rec = self.env['uom.uom'].search([('name', 'ilike', unite)], limit=1)

        # Catégorie INIES
        prod_type_label = PRODUIT_TYPES.get(data.get('produitType'), 'INIES')
        categ = self._get_or_create_category(prod_type_label)

        # Indicateurs environnementaux
        indicators = data.get('tIndicateurQuantites', [])
        ind_dict   = {}
        for ind in indicators:
            ind_dict[f"indicateur_{ind.get('idIndicateurNorme')}_phase_{ind.get('idPhaseNorme')}"] = ind.get('quantite')

        # Documents : construire les URLs
        docs_fdes  = []
        docs_other = []
        for doc in data.get('tDocuments', []):
            path = doc.get('path', '')
            parts = path.split('/')
            encoded = '/'.join(urllib.parse.quote(p, safe='') for p in parts)
            full_url = f"{BASE_URL}/{encoded}"
            if doc.get('docType') == 1:
                docs_fdes.append(full_url)
            elif doc.get('docType') != 6:
                label = DOC_TYPES.get(doc.get('docType'), 'Document')
                docs_other.append(f"{label} : {full_url}")

        vals = {
            'name':              data.get('nomProduit') or product.name,
            'default_code':      data.get('numeroEnregistrement', ''),
            'description_sale':  pd.get('domaineApplication', ''),
            'x_inies_ref':       data.get('numeroEnregistrement', '') or data.get('nationalKey', ''),
            'x_inies_url':       f"{BASE_URL}/consultation/infos-produit/{data.get('idProduit','')}",
            'x_inies_norme':     normes.get(data.get('idNorme'), ''),
            'x_inies_type':      PRODUIT_TYPES.get(data.get('produitType'), ''),
            'x_inies_verification': VERIFICATIONS.get(data.get('verification'), ''),
            'x_inies_date_version': fmt_date(data.get('dateVersion')),
            'x_inies_lieu_prod': '',
            'x_inies_indicators': json.dumps(ind_dict, ensure_ascii=False) if ind_dict else '',
            'x_inies_dvt':       data.get('dvt') or 0,
            'categ_id':          categ.id if categ else product.categ_id.id,
        }
        if uom_rec:
            vals['uom_id'] = uom_rec.id

        product.write(vals)

        # Supprimer les anciens attachments INIES pour ce produit
        inies_id = data.get('idProduit', '')
        fiche_url = f"{BASE_URL}/consultation/infos-produit/{inies_id}"

        old_attachments = self.env['ir.attachment'].search([
            ('res_model', '=', 'product.template'),
            ('res_id',    '=', product.id),
            ('description', 'in', [
                'FDES INIES', 'FDES INIES – voir sur base-inies.fr',
                'Rapport', 'Attestation', 'Documentation',
                'Rapport – voir sur base-inies.fr',
                'Attestation – voir sur base-inies.fr',
                'Documentation – voir sur base-inies.fr',
            ]),
        ])
        old_attachments.unlink()

        # Récupérer tous les PDFs en un seul passage Playwright
        all_docs = (
            [('FDES INIES', url) for url in docs_fdes] +
            [(entry.split(' : ', 1)[0], entry.split(' : ', 1)[1]) for entry in docs_other]
        )
        pdf_map = self._fetch_all_pdfs_playwright(inies_id, [url for _, url in all_docs])

        for label, url in all_docs:
            fname = url.split('/')[-1].split('?')[0] or f"{label}.pdf"
            # Décoder les caractères URL dans le nom de fichier
            try:
                import urllib.parse as _up
                fname = _up.unquote(fname)
            except Exception:
                pass
            pdf_bytes = pdf_map.get(url)
            if pdf_bytes:
                self.env['ir.attachment'].create({
                    'name':        fname,
                    'type':        'binary',
                    'datas':       base64.b64encode(pdf_bytes).decode(),
                    'res_model':   'product.template',
                    'res_id':      product.id,
                    'description': label,
                })
                _logger.info("INIES: attaché %s (%d octets)", fname, len(pdf_bytes))
            else:
                self.env['ir.attachment'].create({
                    'name':        fname,
                    'type':        'url',
                    'url':         fiche_url,
                    'res_model':   'product.template',
                    'res_id':      product.id,
                    'description': f"{label} – voir sur base-inies.fr",
                })

    def _fetch_all_pdfs_playwright(self, inies_id, doc_urls):
        """Capture tous les PDFs INIES via navigateur headless Playwright."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            _logger.warning("INIES: Playwright non installé")
            return {}

        if not doc_urls:
            return {}

        page_url = f"{BASE_URL}/consultation/infos-produit/{inies_id}"
        # Index url→ordre pour associer les PDFs capturés dans l'ordre des clics
        url_order = {u: i for i, u in enumerate(doc_urls)}
        captured_list = []   # [(bytes, resp_url), ...]

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage",
                          "--disable-gpu", "--single-process"],
                )
                ctx = browser.new_context(ignore_https_errors=True,
                                          viewport={"width": 1280, "height": 900})

                def on_response(resp):
                    try:
                        ct = resp.headers.get("content-type", "")
                        if "pdf" in ct or resp.url.lower().endswith(".pdf"):
                            body = resp.body()
                            if len(body) > 1000 and body[:4] == b"%PDF":
                                captured_list.append((body, resp.url))
                                _logger.info("INIES: PDF intercepté %s (%d o)",
                                             resp.url[-60:], len(body))
                    except Exception:
                        pass

                ctx.on("response", on_response)
                page = ctx.new_page()
                page.goto(page_url, wait_until="networkidle", timeout=30000)

                # Accepter les cookies si bannière présente
                try:
                    page.locator(".cc-btn, button:has-text('OK')").first.click(timeout=3000)
                    page.wait_for_timeout(800)
                except Exception:
                    pass

                # Cliquer l'onglet Documents
                try:
                    page.locator("text=Documents").first.click(timeout=5000)
                    page.wait_for_timeout(2500)
                except Exception:
                    pass

                # Cliquer tous les liens dont le texte contient ".pdf"
                all_a = page.locator("a").all()
                for lnk in all_a:
                    try:
                        txt = lnk.inner_text().strip().lower()
                        href = (lnk.get_attribute("href") or "").lower()
                        if ".pdf" in txt or ".pdf" in href:
                            if "mention" in txt:   # ignorer "Mentions légales"
                                continue
                            lnk.click(timeout=4000)
                            page.wait_for_timeout(2500)
                    except Exception:
                        pass

                page.wait_for_timeout(2000)
                browser.close()

        except Exception as e:
            _logger.warning("INIES: erreur Playwright produit %s : %s", inies_id, e)
            return {}

        # L'endpoint INIES renvoie toujours /api/downloadDocument/ sans nom de fichier.
        # On associe dans l'ordre d'apparition sur la page (= ordre du clic).
        result = {}
        for i, doc_url in enumerate(doc_urls):
            if i < len(captured_list):
                result[doc_url] = captured_list[i][0]

        _logger.info("INIES: %d/%d PDFs récupérés pour produit %s",
                     len(result), len(doc_urls), inies_id)
        return result

    def _get_or_create_category(self, type_label):
        """Retourne ou crée la catégorie INIES / <type>."""
        parent = self.env['product.category'].search(
            [('name', '=', 'INIES'), ('parent_id', '=', False)], limit=1)
        if not parent:
            parent = self.env['product.category'].create({'name': 'INIES'})
        categ = self.env['product.category'].search(
            [('name', '=', type_label), ('parent_id', '=', parent.id)], limit=1)
        if not categ:
            categ = self.env['product.category'].create(
                {'name': type_label, 'parent_id': parent.id})
        return categ


class InesSearchWizard(models.TransientModel):
    _name        = 'inies.search.wizard'
    _description = 'Wizard de recherche INIES'

    product_id   = fields.Many2one('product.template', string='Produit cible',
                                    required=True, ondelete='cascade')
    search_mode  = fields.Selection([
        ('nom', 'Par nom'),
        ('ref', 'Par référence'),
        ('key', 'Par clé INIES'),
        ('id',  'Par ID'),
    ], string='Mode de recherche', default='nom', required=True)
    search_value = fields.Char(string='Valeur', required=True)
    result_ids   = fields.One2many('inies.search.result', 'wizard_id',
                                    string='Résultats')
    state        = fields.Selection([
        ('search',  'Recherche'),
        ('results', 'Résultats'),
    ], default='search')
    result_count = fields.Integer(string='Nombre de résultats', compute='_compute_result_count')
    error_msg    = fields.Char(string='Erreur')

    @api.depends('result_ids')
    def _compute_result_count(self):
        for rec in self:
            rec.result_count = len(rec.result_ids)

    def action_search(self):
        self.ensure_one()
        self.error_msg = False
        self.result_ids.unlink()

        try:
            product_ids = self._fetch_product_ids()
        except Exception as e:
            self.error_msg = str(e)
            self.state = 'search'
            return self._reopen()

        if not product_ids:
            self.error_msg = f"Aucun résultat pour « {self.search_value} »"
            self.state = 'search'
            return self._reopen()

        # Charger les infos légères pour l'affichage
        try:
            normes = {n['idNorme']: n.get('nomNorme', n.get('nom', ''))
                      for n in _api_get("/api/Norme")}
        except Exception:
            normes = {}

        results = []
        for pid in product_ids[:50]:
            try:
                p = _api_get(f"/api/Produit/{pid}")
                results.append({
                    'wizard_id':        self.id,
                    'inies_id':         p.get('idProduit'),
                    'nom':              p.get('nomProduit', ''),
                    'ref':              p.get('numeroEnregistrement', ''),
                    'type_declaration': PRODUIT_TYPES.get(p.get('produitType'), ''),
                    'statut':           STATUTS.get(p.get('statut'), ''),
                    'norme':            normes.get(p.get('idNorme'), ''),
                    'data_json':        json.dumps(p),
                })
            except Exception:
                pass

        self.env['inies.search.result'].create(results)
        self.state = 'results'
        return self._reopen()

    def action_reset(self):
        self.result_ids.unlink()
        self.state  = 'search'
        self.error_msg = False
        return self._reopen()

    def _fetch_product_ids(self):
        mode  = self.search_mode
        value = self.search_value.strip()

        if mode == 'id':
            try:
                return [int(value)]
            except ValueError:
                raise UserError(f"ID invalide : {value}")

        if mode in ('ref', 'key'):
            all_products = _api_get("/api/GetOnlineProduitVMList")
            val_lower    = value.lower()
            return [
                p['idProduit'] for p in all_products
                if val_lower in ((p.get('numeroEnregistrement') or '').lower(),
                                 (p.get('nationalKey') or '').lower())
            ]

        # mode == 'nom'
        return _api_post("/api/SearchProduits", {
            "typeDeclaration": 0, "cov": 0, "onlineDate": 0,
            "lieuProduction": 0, "perfUF": 0, "qtPerfUF": None,
            "norme": 0, "organisme": None, "selectedNomenclature": None,
            "onlyArchive": False, "nomProduit": value,
        })

    def _reopen(self):
        return {
            'type':      'ir.actions.act_window',
            'res_model': 'inies.search.wizard',
            'res_id':    self.id,
            'view_mode': 'form',
            'target':    'new',
        }
