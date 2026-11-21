# kotlinx.serialization: generierte Serializer behalten
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers @kotlinx.serialization.Serializable class io.github.elitap.co2ampel.** {
    *** Companion;
    kotlinx.serialization.KSerializer serializer(...);
}
-keepclasseswithmembers class io.github.elitap.co2ampel.** {
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class io.github.elitap.co2ampel.**$$serializer { *; }

# OkHttp bringt eigene Regeln mit; optionale Abhängigkeiten nicht melden
-dontwarn org.bouncycastle.**
-dontwarn org.conscrypt.**
-dontwarn org.openjsse.**
