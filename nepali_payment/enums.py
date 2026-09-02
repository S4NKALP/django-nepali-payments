from enum import Enum


class PaymentMethod(str, Enum):
    """Supported payment gateways"""

    ESEWA = "Esewa"
    KHALTI = "Khalti"
    FONEPAY = "FonePay"
    CONNECTIPS = "ConnectIps"


class PaymentMode(str, Enum):
    """Environment mode controlling which endpoints are used"""

    SANDBOX = "Sandbox"
    PRODUCTION = "Production"


class PaymentAction(str, Enum):
    """The operation to perform against a gateway"""

    PROCESS_PAYMENT = "ProcessPayment"
    VERIFY_PAYMENT = "VerifyPayment"
    CHECK_PAYMENT = "CheckPayment"
