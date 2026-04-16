import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Supprime la colonne x_inies_indicators de la table product_template
    cr.execute("""
        ALTER TABLE product_template
        DROP COLUMN IF EXISTS x_inies_indicators
    """)
    _logger.info("INIES migration: colonne x_inies_indicators supprimée")

    # Supprime l'enregistrement ir.model.fields résiduel
    cr.execute("""
        DELETE FROM ir_model_fields
        WHERE model = 'product.template'
          AND name  = 'x_inies_indicators'
    """)
    _logger.info("INIES migration: ir.model.fields x_inies_indicators supprimé")
