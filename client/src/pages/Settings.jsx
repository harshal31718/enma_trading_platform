import PageWrapper from '@/components/layout/PageWrapper'
import PageHeader from '@/components/ui/PageHeader'
import ProfileCard from '@/features/settings/ProfileCard'
import AlgoAccessCard from '@/features/settings/AlgoAccessCard'
import EnvironmentConfigCard from '@/features/settings/EnvironmentConfigCard'
import ChaosSettingsCard from '@/features/settings/ChaosSettingsCard'
import NotificationsCard from '@/features/settings/NotificationsCard'
import ExchangeSettingsCard from '@/features/settings/ExchangeSettingsCard'

export default function Settings() {
  return (
    <PageWrapper>
      <PageHeader title="Settings" />

      <ProfileCard />
      <AlgoAccessCard />

      <div className="mx-auto max-w-6xl grid grid-cols-1 lg:grid-cols-2 gap-0 items-start">
        <div className="space-y-0">
          <EnvironmentConfigCard />
          <ChaosSettingsCard />
          <NotificationsCard />
        </div>

        <ExchangeSettingsCard />
      </div>

    </PageWrapper>
  )
}
