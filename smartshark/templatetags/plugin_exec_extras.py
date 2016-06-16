from django.template.defaulttags import register

@register.filter
def get_item(dictionary, key):
    print(key)
    print(dictionary)
    return dictionary.get(key)