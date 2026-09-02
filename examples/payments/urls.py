"""URL routes for the example payments app."""

from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("", views.home, name="payments-home"),
    path("new/<str:gateway>/", views.create_order, name="payments-create"),
    path("static-qr/", views.static_qr, name="payments-static-qr"),
    path("connectips-payment/", views.connectips_payment, name="payments-connectips-payment"),
    path("verify/<int:order_id>/", views.verify_order, name="payments-verify"),
    path("callback/<str:gateway>/", views.callback, name="payments-callback"),
    path("failure/<str:gateway>/", views.failure, name="payments-failure"),
]
