import type { ChatMessage } from '../api/types'
import { MiniJobCard } from './MiniJobCard'

interface ChatMessageBubbleProps {
  message: ChatMessage
  onRateJob: (jobId: string, feedback: 'relevant' | 'not_relevant') => void
  onTailorJob: (jobId: string) => void
}

/**
 * Renders one chat turn. A message can carry either plain text, a list of
 * job-card payloads, or both (per the brief: "structure your
 * message-rendering component so a message can carry either plain text or
 * a list of job-card payloads") -- tool results that represent jobs render
 * as structured MiniJobCards rather than flattened into the text body.
 */
export function ChatMessageBubble({ message, onRateJob, onTailorJob }: ChatMessageBubbleProps) {
  return (
    <div className={`chat-message ${message.role}`} data-testid="chat-message">
      {message.content && <div>{message.content}</div>}
      {message.jobs && message.jobs.length > 0 && (
        <div>
          {message.jobs.map((job) => (
            <MiniJobCard
              key={job.job_id}
              job={job}
              onRate={(feedback) => onRateJob(job.job_id, feedback)}
              onTailor={() => onTailorJob(job.job_id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
