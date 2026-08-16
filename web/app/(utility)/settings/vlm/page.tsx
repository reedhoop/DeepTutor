"use client";

import { useTranslation } from "react-i18next";

import { ServiceConfigEditor } from "@/components/settings/ServiceConfigEditor";
import { SettingsPageHeader } from "@/components/settings/shared";

export default function VlmSettingsPage() {
  const { t } = useTranslation();
  return (
    <div>
      <SettingsPageHeader
        title={t("VLM")}
        description={t(
          "Configure the explicit vision-language model (VLM) slot. When the active LLM lacks native vision, image attachments are routed here for understanding (T1 fallback tier).",
        )}
      />
      <ServiceConfigEditor service="vlm" />
    </div>
  );
}
