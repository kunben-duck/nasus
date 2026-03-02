package com.autotest.platform.dto;

import com.autotest.platform.entity.NotificationMessage;
import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class NotificationDTO {
    private Long id;
    private NotificationMessage.NotificationType type;
    private NotificationMessage.NotificationLevel level;
    private String title;
    private String content;
    private String relatedResourceType;
    private String relatedResourceId;
    private boolean read;
    private LocalDateTime createdAt;
    private LocalDateTime readAt;
}
