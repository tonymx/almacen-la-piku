# coding=utf-8

import re
import datetime
from functools import partial

from django import forms
from django.contrib import admin
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect

from cliente.models import (
    Cliente, PedidoCliente, DetallePedidoCliente,
    DevolucionPedidoCliente, DetalleDevolucionPedidoCliente,
)
from producto.models import Producto
from general import app_messages


# Cliente
class ClienteCreationForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ['nombre', 'nit', 'telefono']

    def clean_nombre(self):
        nombre = self.cleaned_data.get("nombre")
        if re.match("^([a-zA-ZñÑáéíóúÁÉÍÓÚ_-]\s?)+$", nombre) is None:
            raise forms.ValidationError(app_messages.NAME_MUST_BE_VALID)
        return nombre

    def clean_nit(self):
        nit = self.cleaned_data.get("nit")
        if nit.isdigit() is False:
            raise forms.ValidationError(app_messages.NIT_MUST_BE_VALID)
        return nit

    def save(self, commit=True):
        cliente = super(ClienteCreationForm, self).save(commit=False)
        if commit:
            cliente.save()
        return cliente


class ClienteAdmin(admin.ModelAdmin):
    form = ClienteCreationForm

    list_display = ['nombre', 'nit', 'telefono']
    search_fields = ['nombre', 'nit', 'telefono']


# Pedido Cliente
class DetallePedidoClienteFormset(forms.BaseInlineFormSet):
    def clean(self):
        # self.instance makes referense to PedidoCliente

        for form in self.forms:
            try:
                producto = form.instance.producto
                cantidad_solicitada = form.instance.cantidad_solicitada
                cantidad_entregada = form.instance.cantidad_entregada
                if cantidad_solicitada > producto.stock:
                    raise forms.ValidationError(app_messages.CANTIDAD_SOLICITADA_DOES_NOT_EXISTS)
                elif cantidad_solicitada < 0:
                    raise forms.ValidationError(app_messages.CANTIDAD_SOLICITADA_MUST_BE_POSITIVE)
                elif cantidad_entregada > cantidad_solicitada:
                    raise forms.ValidationError(app_messages.CANTIDAD_ENTREGADA_MUST_BE_LESS)
                elif cantidad_entregada < 0:
                    raise forms.ValidationError(app_messages.CANTIDAD_ENTREGADA_MUST_BE_POSITIVE)
            except Producto.DoesNotExist:
                pass


class DetallePedidoClienteInline(admin.TabularInline):
    formset = DetallePedidoClienteFormset
    extra = 1
    fields = ['producto', 'cantidad_solicitada', 'cantidad_entregada', 'precio_venta']
    min_num = 1
    model = DetallePedidoCliente
    show_change_link = False


class PedidoClienteForm(forms.ModelForm):
    class Meta:
        model = PedidoCliente
        fields = ['cliente', 'total_pagado']

    def clean_total_pagado(self):
        total_pagado = self.cleaned_data.get("total_pagado")
        if total_pagado < 0:
            raise forms.ValidationError(app_messages.TOTAL_PAGADO_MUST_BE_POSITIVE)
        elif total_pagado > float(self.instance.precio_total):
            raise forms.ValidationError(app_messages.TOTAL_PAGADO_MUST_BE_LESS)
        return total_pagado


class PedidoClienteAdmin(admin.ModelAdmin):
    form = PedidoClienteForm

    fields = ['cliente']
    inlines = [DetallePedidoClienteInline]
    list_display = ('cliente', 'fecha_pedido', 'precio_total', 'total_pagado', 'saldo', 'cancelado', )
    list_editable = ('total_pagado', )
    list_filter = ('fecha_pedido', )
    search_fields = ['fecha_pedido', 'cliente__nombre']
    actions = ['generar_pdf']

    def get_changelist_formset(self, request, **kwargs):
        defaults = {
            "formfield_callback": partial(super(PedidoClienteAdmin, self).formfield_for_dbfield, request=request),
            "form": PedidoClienteForm,
        }
        defaults.update(kwargs)
        return forms.models.modelformset_factory(PedidoCliente,
                                                 extra=0,
                                                 fields=self.list_editable, **defaults)

    def generar_pdf(self, request, queryset):
        id = queryset[0].id
        pedido_id = PedidoCliente.encryptId(id)
        url = reverse('cliente:factura_pdf', kwargs={'pedido_id': pedido_id})
        return HttpResponseRedirect(url)

    generar_pdf.short_description = "Generar recibo"

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)

        for obj in formset.deleted_objects:
            if obj.cantidad_entregada is None:
                obj.cantidad_entregada = 0
            producto = obj.producto
            producto.stock += obj.cantidad_entregada
            producto.save()
            obj.delete()
        for instance in instances:

            if instance.cantidad_entregada is None:
                instance.cantidad_entregada = 0
            if instance.cantidad_entregada_anterior is None:
                instance.cantidad_entregada_anterior = 0
            producto = instance.producto

            if instance.cantidad_entregada > instance.cantidad_entregada_anterior:
                cantidad_entregada = instance.cantidad_entregada - instance.cantidad_entregada_anterior
                producto.stock -= cantidad_entregada
            else:
                cantidad_entregada = instance.cantidad_entregada_anterior - instance.cantidad_entregada
                producto.stock += cantidad_entregada

            instance.cantidad_entregada_anterior = instance.cantidad_entregada

            producto.save()
            instance.save()
            formset.save_m2m()


# Devolucion Pedido Cliente
class DetalleDevolucionPedidoClienteInline(admin.TabularInline):
    model = DetalleDevolucionPedidoCliente
    extra = 1
    min_num = 1
    show_change_link = False


class DevolucionPedidoClienteCreationForm(forms.ModelForm):
    class Meta:
        model = DevolucionPedidoCliente
        fields = ['cliente', 'detalle']

    def clean_fecha_devolucion(self):
        fecha_devolucion = self.cleaned_data.get("fecha_devolucion")
        if fecha_devolucion < datetime.date.today():
            raise forms.ValidationError(app_messages.DATE_MUST_BE_GREATER)
        return fecha_devolucion


class DevolucionPedidoClienteAdmin(admin.ModelAdmin):
    form = DevolucionPedidoClienteCreationForm

    fields = ['cliente', 'detalle']
    list_filter = ['fecha_devolucion']
    search_fields = ['cliente__nombre']
    list_display = ['cliente', 'fecha_devolucion', 'detalle']
    inlines = [DetalleDevolucionPedidoClienteInline]

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            producto = obj.producto
            producto.stock -= obj.cantidad_devuelta
            producto.save()
            obj.delete()
        for instance in instances:
            producto = instance.producto
            producto.stock += instance.cantidad_devuelta
            producto.save()
            instance.save()
        formset.save_m2m()


admin.site.register(Cliente, ClienteAdmin)
admin.site.register(PedidoCliente, PedidoClienteAdmin)
admin.site.register(DevolucionPedidoCliente, DevolucionPedidoClienteAdmin)
