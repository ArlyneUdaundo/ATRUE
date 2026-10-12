from django.contrib import admin

from .models import Barangay, CityMunicipality, Country, Province, Region


class RegionInline(admin.TabularInline):
    model = Region
    extra = 0
    fields = ('code', 'name')
    show_change_link = True


class ProvinceInline(admin.TabularInline):
    model = Province
    extra = 0
    fields = ('code', 'name')
    show_change_link = True


class CityMunicipalityInline(admin.TabularInline):
    model = CityMunicipality
    extra = 0
    fields = ('code', 'name')
    show_change_link = True


class BarangayInline(admin.TabularInline):
    model = Barangay
    extra = 0
    fields = ('name',)
    show_change_link = True


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'region_count')
    search_fields = ('name', 'code', 'asciiname')
    ordering = ('name',)
    inlines = [RegionInline]

    @admin.display(description='Regions')
    def region_count(self, obj):
        return obj.regions.count()


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'country')
    list_filter = ('country',)
    search_fields = ('code', 'name', 'country__name')
    ordering = ('name',)
    inlines = [ProvinceInline]


@admin.register(Province)
class ProvinceAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'region', 'country')
    list_filter = ('region__country', 'region')
    search_fields = ('name', 'code', 'region__name', 'region__country__name')
    inlines = [CityMunicipalityInline]

    @admin.display(description='Country', ordering='region__country__name')
    def country(self, obj):
        return obj.region.country.name


@admin.register(CityMunicipality)
class CityMunicipalityAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'province')
    list_filter = ('province__region',)
    search_fields = ('name', 'code', 'province__name')
    inlines = [BarangayInline]


@admin.register(Barangay)
class BarangayAdmin(admin.ModelAdmin):
    list_display = ('name', 'city_municipality', 'city_municipality__province')
    list_filter = ('city_municipality__province',)
    search_fields = ('name', 'city_municipality__name', 'city_municipality__province__name')
