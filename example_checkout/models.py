# -*- encoding: utf-8 -*-
from django.core.urlresolvers import reverse
from django.db import models

from checkout.models import (
#    default_payment_state,
#    Payment,
#    PaymentLine,
#    PaymentState,
    CheckoutState,
    default_checkout_state,
    Checkout,
)
from finance.models import VatSettings
#from pay.service import (
#    PAYMENT_LATER,
#    PAYMENT_THANKYOU,
#)
from stock.models import Product


class SalesLedgerManager(models.Manager):

    def create_sales_ledger(self, email, description, product, quantity):
        obj = self.model(
            email=email,
            description=description,
            product=product,
            quantity=quantity,
        )
        obj.save()
        return obj


class SalesLedger(models.Model):
    """List of prices."""

    email = models.EmailField()
    description = models.CharField(max_length=100)
    product = models.ForeignKey(Product)
    quantity = models.IntegerField()
    checkout_state = models.ForeignKey(
        CheckoutState,
        default=default_checkout_state,
    )
    objects = SalesLedgerManager()

    class Meta:
        ordering = ('pk',)
        verbose_name = 'Sales ledger'
        verbose_name_plural = 'Sales ledger'

    def __str__(self):
        return '{}'.format(self.description)

    def get_absolute_url(self):
        """just for testing."""
        return reverse('project.home')

    #def allow_pay_later(self):
    #    return False

    def create_checkout(self, token):
        """Example payment.

        Note: Must be called from within a transaction.

        """
        return Checkout.objects.create_checkout(
            self.email, self.description, token, self
        )
        #vat_settings = VatSettings.objects.settings()
        #PaymentLine.objects.create_payment_line(
        #    payment=payment,
        #    product=self.product,
        #    quantity=self.quantity,
        #    units='each',
        #    vat_code=vat_settings.standard_vat_code,
        #)
        return payment

    @property
    def is_paid(self):
        return self.payment_state == CheckoutState.objects.success

    @property
    def can_pay(self):
        return self.checkout_state == CheckoutState.objects.pending

    @property
    def mail_template_name(self):
        """Which mail template to use.

        We don't allow pay later (see 'allow_pay_later' above).

        """
        return 'PAYMENT_THANKYOU'

    def set_checkout_state(self, checkout_state):
        self.checkout_state = checkout_state
        self.save()

    @property
    def checkout_description(self):
        return [self.description]

    @property
    def checkout_email(self):
        return self.email

    @property
    def checkout_total(self):
        return self.product.price * self.quantity
