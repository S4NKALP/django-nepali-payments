class Esewa:
    """eSewa endpoint constants."""

    BASE_URL = "https://epay.esewa.com.np/api/epay/main/v2/form"
    SANDBOX_BASE_URL = "https://rc-epay.esewa.com.np/api"
    PROCESS_PAYMENT_URL = "/epay/main/v2/form"
    VERIFY_PAYMENT_URL = "/epay/transaction/status/"
    PAYMENT_CHECK_URL = "/epay/transaction/status/"
    PROCESS_PAYMENT_METHOD = "POST"
    VERIFY_PAYMENT_METHOD = "GET"
    PAYMENT_CHECK_METHOD = "GET"


class Khalti:
    """Khalti endpoint constants."""

    BASE_URL = "https://api.khalti.com/"
    SANDBOX_BASE_URL = "https://a.khalti.com/api/"
    PROCESS_PAYMENT_URL = "epayment/initiate/"
    VERIFY_PAYMENT_URL = "epayment/lookup/"
    PAYMENT_CHECK_URL = "epayment/lookup/"
    PROCESS_PAYMENT_METHOD = "POST"
    VERIFY_PAYMENT_METHOD = "POST"
    PAYMENT_CHECK_METHOD = "GET"


class Fonepay:
    """Fonepay endpoint constants."""

    BASE_URL = "https://merchantapi.fonepay.com/api"
    SANDBOX_BASE_URL = "https://dev-merchantapi.fonepay.com/api"
    QR_GENERATE_URL = "/merchant/merchantDetailsForThirdParty/thirdPartyDynamicQrDownload"
    QR_STATUS_URL = "/merchant/merchantDetailsForThirdParty/thirdPartyDynamicQrGetStatus"
    STATIC_QR_URL = "/merchant/merchantDetailsForThirdParty/thirdPartyStaticQrDownload"
    TAX_REFUND_URL = "/merchant/merchantDetailsForThirdParty/thirdPartyPostTaxRefund"
    QR_GENERATE_METHOD = "POST"
    QR_STATUS_METHOD = "POST"
    STATIC_QR_METHOD = "POST"
    TAX_REFUND_METHOD = "POST"
    WEB_SOCKET_URL = "wss://ws.fonepay.com/convergent-webSocket-web/merchantEndPoint"
    SANDBOX_WEB_SOCKET_URL = "wss://dev-ws.fonepay.com/convergent-webSocket-web/merchantEndPoint"


class ConnectIps:
    """ConnectIPS endpoint constants (form POST + validation API)."""

    LOGIN_URL = "https://connectips.com/connectipswebgw/loginpage"
    SANDBOX_LOGIN_URL = "https://uat.connectips.com/connectipswebgw/loginpage"
    VALIDATION_URL = "https://connectips.com/connectipswebws/api/creditor/validatetxn"
    SANDBOX_VALIDATION_URL = "https://uat.connectips.com/connectipswebws/api/creditor/validatetxn"
    LOGIN_METHOD = "POST"
    VALIDATION_METHOD = "POST"


class ApiEndpoints:
    """Root grouping of all provider endpoint constants."""

    ESEWA = Esewa
    KHALTI = Khalti
    FONEPAY = Fonepay
    CONNECTIPS = ConnectIps
