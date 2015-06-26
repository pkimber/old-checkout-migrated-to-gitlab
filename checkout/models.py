# -*- encoding: utf-8 -*-
import logging

from django.contrib.contenttypes import generic
from django.contrib.contenttypes.models import ContentType
from django.db import models

import reversion
import stripe

from base.model_utils import TimeStampedModel
from mail.models import Notify
from mail.service import queue_mail_message


logger = logging.getLogger(__name__)


def default_checkout_state():
    return CheckoutState.objects.get(slug=CheckoutState.PENDING).pk


def log_stripe_error(log, e, message):
    log.error(
        'StripeError\n'
        '{}\n'
        'http body: {}\n'
        'http status: {}'.format(
            message,
            e.http_body,
            e.http_status,
        )
    )


class CheckoutError(Exception):

    def __init__(self, value):
        Exception.__init__(self)
        self.value = value

    def __str__(self):
        return repr('%s, %s' % (self.__class__.__name__, self.value))


class CheckoutStateManager(models.Manager):

    @property
    def fail(self):
        return self.model.objects.get(slug=self.model.FAIL)

    @property
    def pending(self):
        return self.model.objects.get(slug=self.model.PENDING)

    @property
    def success(self):
        return self.model.objects.get(slug=self.model.SUCCESS)


class CheckoutState(TimeStampedModel):

    FAIL = 'fail'
    PENDING = 'pending'
    SUCCESS = 'success'

    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    objects = CheckoutStateManager()

    class Meta:
        ordering = ('name',)
        verbose_name = 'Checkout state'
        verbose_name_plural = 'Checkout states'

    def __str__(self):
        return '{}'.format(self.name)

reversion.register(CheckoutState)


class CheckoutActionManager(models.Manager):

    @property
    def payment(self):
        return self.model.objects.get(slug=self.model.PAYMENT)


class CheckoutAction(TimeStampedModel):

    PAYMENT = 'payment'
    PAYMENT_PLAN = 'payment_plan'

    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    objects = CheckoutActionManager()

    class Meta:
        ordering = ('name',)
        verbose_name = 'Checkout action'
        verbose_name_plural = 'Checkout action'

    def __str__(self):
        return '{}'.format(self.name)

reversion.register(CheckoutAction)


class CustomerManager(models.Manager):

    def _create_customer(self, name, email, customer_id):
        obj = self.model(name=name, email=email, customer_id=customer_id)
        obj.save()
        return obj

    def _stripe_create(self, email, description, token):
        """Use the Stripe API to create a customer."""
        try:
            customer = stripe.Customer.create(
                email=email,
                description=description,
                card=token,
            )
            return customer.id
        except stripe.StripeError as e:
            log_stripe_error(logger, e, 'create - email: {}'.format(email))
            raise

    def _stripe_update(self, customer_id, description, token):
        """Use the Stripe API to update a customer."""
        try:
            stripe_customer = stripe.Customer.retrieve(customer_id)
            stripe_customer.description = description
            stripe_customer.card = token
            stripe_customer.save()
        except stripe.StripeError as e:
            log_stripe_error(logger, e, 'update - id: {}'.format(customer_id))
            raise

    def init_customer(self, name, email, token):
        """Initialise Stripe customer using email, description and token.

        1. Lookup existing customer record in the database.

           - Retrieve customer from Stripe and update description and token.

        2. If the customer does not exist:

          - Create Stripe customer with email, description and token.
          - Create a customer record in the database.

        Return the customer database record.

        """
        try:
            obj = self.model.objects.get(email=email)
            obj.name = name
            obj.save()
            self._stripe_update(obj.customer_id, name, token)
        except self.model.DoesNotExist:
            customer_id = self._stripe_create(email, name, token)
            obj = self._create_customer(name, email, customer_id)
        return obj


class Customer(TimeStampedModel):
    """Stripe Customer.

    Link the Stripe customer to an email address (and name).

    Note: It is expected that multiple users in our databases could have the
    same email address.  If they have different names, then this table looks
    very confusing.  Try checking the 'content_object' of the 'Checkout' model
    if you need to diagnose an issue.

    """

    name = models.TextField()
    email = models.EmailField(unique=True)
    customer_id = models.TextField()
    objects = CustomerManager()

    class Meta:
        ordering = ('pk',)
        verbose_name = 'Customer'
        verbose_name_plural = 'Customers'

    def __str__(self):
        return '{} {}'.format(self.email, self.customer_id)

reversion.register(Customer)


class CheckoutManager(models.Manager):

    def create_checkout(
            self, action, name, email, description, token, content_object):
        """Create a checkout payment request."""
        customer = Customer.objects.init_customer(name, email, token)
        obj = self.model(
            action=action,
            content_object=content_object,
            customer=customer,
            description=description,
        )
        obj.save()
        return obj

    def audit(self):
        return self.model.objects.all().order_by('-pk')

    def payments(self):
        return self.audit().filter(
            action=CheckoutAction.objects.payment,
            state=CheckoutState.objects.success,
        )


class Checkout(TimeStampedModel):
    """Checkout."""

    action = models.ForeignKey(CheckoutAction)
    customer = models.ForeignKey(Customer)
    state = models.ForeignKey(CheckoutState, default=default_checkout_state)
    description = models.TextField()
    total = models.DecimalField(
        max_digits=8, decimal_places=2, blank=True, null=True
    )
    # link to the object in the system which requested the checkout
    content_type = models.ForeignKey(ContentType)
    object_id = models.PositiveIntegerField()
    content_object = generic.GenericForeignKey()
    objects = CheckoutManager()

    class Meta:
        ordering = ('pk',)
        verbose_name = 'Checkout'
        verbose_name_plural = 'Checkouts'

    def __str__(self):
        return '{}'.format(self.customer.email)

    def _notify(self, request):
        email_addresses = [n.email for n in Notify.objects.all()]
        if email_addresses:
            caption = self.action.name
            subject = '{} from {}'.format(
                caption.capitalize(),
                self.customer.name,
            )
            message = '{} - {} from {}, {}:'.format(
                self.created.strftime('%d/%m/%Y %H:%M'),
                caption,
                self.customer.name,
                self.customer.email,
            )
            message = message + '\n\n{}\n\n{}'.format(
                self.description,
                request.build_absolute_uri(self.content_object_url),
            )
            queue_mail_message(
                self,
                email_addresses,
                subject,
                message,
            )
        else:
            logging.error(
                "Cannot send email notification of checkout transaction.  "
                "No email addresses set-up in 'enquiry.models.Notify'"
            )

    def _success_or_fail(self, state, request):
        self.state = state
        self.save()
        self._notify(request)

    @property
    def content_object_url(self):
        try:
            return self.content_object.get_absolute_url()
        except AttributeError:
            return None

    @property
    def fail(self, request):
        """Checkout failed - so update and notify admin."""
        self._success_or_fail(CheckoutState.objects.fail, request)
        return self.content_object.checkout_fail

    @property
    def failed(self):
        """Did the checkout request fail?"""
        return self.state == CheckoutState.objects.fail

    @property
    def payment(self):
        """Is this a payment action."""
        return self.action == CheckoutAction.objects.payment

    def success(self, request):
        """Checkout successful - so update and notify admin."""
        self._success_or_fail(CheckoutState.objects.success, request)
        return self.content_object.checkout_success

reversion.register(Checkout)
