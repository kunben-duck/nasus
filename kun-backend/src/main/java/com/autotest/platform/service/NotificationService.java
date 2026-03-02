package com.autotest.platform.service;

import com.autotest.platform.dto.NotificationDTO;
import com.autotest.platform.dto.NotificationFeedDTO;
import com.autotest.platform.dto.NotificationBatchDeleteResultDTO;
import com.autotest.platform.dto.NotificationReadAllResultDTO;
import com.autotest.platform.dto.PageResponse;
import com.autotest.platform.entity.NotificationMessage;
import com.autotest.platform.entity.User;
import com.autotest.platform.repository.NotificationMessageRepository;
import com.autotest.platform.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Objects;

@Service
@RequiredArgsConstructor
@Slf4j
public class NotificationService {

    private final NotificationMessageRepository notificationMessageRepository;
    private final UserRepository userRepository;
    private final TenantContextService tenantContextService;

    @Transactional
    public void publishToUser(String username,
                              Long tenantId,
                              NotificationMessage.NotificationType type,
                              NotificationMessage.NotificationLevel level,
                              String title,
                              String content,
                              String relatedResourceType,
                              String relatedResourceId) {
        if (username == null || username.trim().isEmpty() || tenantId == null || type == null) {
            return;
        }
        User user = userRepository.findByUsername(username.trim()).orElse(null);
        if (user == null) {
            log.warn("Skip notification publish: user not found. username={}", username);
            return;
        }

        NotificationMessage message = NotificationMessage.builder()
                .userId(user.getId())
                .tenantId(tenantId)
                .type(type)
                .level(level == null ? NotificationMessage.NotificationLevel.INFO : level)
                .title(trimToLength(title, 200, "系统消息"))
                .content(trimToLength(content, 4000, ""))
                .relatedResourceType(trimToLength(relatedResourceType, 64, null))
                .relatedResourceId(trimToLength(relatedResourceId, 128, null))
                .read(Boolean.FALSE)
                .build();
        notificationMessageRepository.save(message);
    }

    @Transactional(readOnly = true)
    public NotificationFeedDTO getNotifications(String username, int page, int size, boolean unreadOnly) {
        TenantContextService.CurrentTenant current = tenantContextService.resolveCurrentTenant(username);
        Long userId = current.user().getId();
        Long tenantId = current.tenant().getId();

        int normalizedPage = Math.max(0, page);
        int normalizedSize = Math.max(1, Math.min(size, 100));
        Pageable pageable = PageRequest.of(normalizedPage, normalizedSize);

        Page<NotificationMessage> sourcePage = unreadOnly
                ? notificationMessageRepository.findByUserIdAndTenantIdAndReadFalseOrderByCreatedAtDesc(userId, tenantId, pageable)
                : notificationMessageRepository.findByUserIdAndTenantIdOrderByCreatedAtDesc(userId, tenantId, pageable);
        Page<NotificationDTO> mappedPage = sourcePage.map(this::toDto);
        long unreadCount = notificationMessageRepository.countByUserIdAndTenantIdAndReadFalse(userId, tenantId);

        return NotificationFeedDTO.builder()
                .page(PageResponse.from(mappedPage))
                .unreadCount(unreadCount)
                .build();
    }

    @Transactional
    public NotificationDTO markAsRead(String username, Long notificationId) {
        if (notificationId == null) {
            throw new RuntimeException("通知ID不能为空");
        }
        TenantContextService.CurrentTenant current = tenantContextService.resolveCurrentTenant(username);
        NotificationMessage message = notificationMessageRepository
                .findByIdAndUserIdAndTenantId(notificationId, current.user().getId(), current.tenant().getId())
                .orElseThrow(() -> new RuntimeException("通知不存在或无权限访问"));

        if (!Boolean.TRUE.equals(message.getRead())) {
            message.setRead(Boolean.TRUE);
            message.setReadAt(LocalDateTime.now());
            message = notificationMessageRepository.save(message);
        }
        return toDto(message);
    }

    @Transactional
    public NotificationReadAllResultDTO markAllAsRead(String username) {
        TenantContextService.CurrentTenant current = tenantContextService.resolveCurrentTenant(username);
        int updated = notificationMessageRepository.markAllAsRead(
                current.user().getId(),
                current.tenant().getId(),
                LocalDateTime.now()
        );
        long unreadCount = notificationMessageRepository.countByUserIdAndTenantIdAndReadFalse(
                current.user().getId(),
                current.tenant().getId()
        );
        return NotificationReadAllResultDTO.builder()
                .updatedCount(updated)
                .unreadCount(unreadCount)
                .build();
    }

    @Transactional
    public void deleteNotification(String username, Long notificationId) {
        if (notificationId == null) {
            throw new RuntimeException("通知ID不能为空");
        }
        TenantContextService.CurrentTenant current = tenantContextService.resolveCurrentTenant(username);
        NotificationMessage message = notificationMessageRepository
                .findByIdAndUserIdAndTenantId(notificationId, current.user().getId(), current.tenant().getId())
                .orElseThrow(() -> new RuntimeException("通知不存在或无权限访问"));
        notificationMessageRepository.delete(message);
    }

    @Transactional
    public NotificationBatchDeleteResultDTO deleteNotifications(String username, List<Long> notificationIds) {
        if (notificationIds == null || notificationIds.isEmpty()) {
            throw new RuntimeException("请至少选择一条消息");
        }
        List<Long> ids = notificationIds.stream()
                .filter(Objects::nonNull)
                .distinct()
                .toList();
        if (ids.isEmpty()) {
            throw new RuntimeException("请至少选择一条有效消息");
        }
        TenantContextService.CurrentTenant current = tenantContextService.resolveCurrentTenant(username);
        int deletedCount = notificationMessageRepository.deleteByUserIdAndTenantIdAndIds(
                current.user().getId(),
                current.tenant().getId(),
                ids
        );
        long unreadCount = notificationMessageRepository.countByUserIdAndTenantIdAndReadFalse(
                current.user().getId(),
                current.tenant().getId()
        );
        return NotificationBatchDeleteResultDTO.builder()
                .deletedCount(deletedCount)
                .unreadCount(unreadCount)
                .build();
    }

    private NotificationDTO toDto(NotificationMessage source) {
        return NotificationDTO.builder()
                .id(source.getId())
                .type(source.getType())
                .level(source.getLevel())
                .title(source.getTitle())
                .content(source.getContent())
                .relatedResourceType(source.getRelatedResourceType())
                .relatedResourceId(source.getRelatedResourceId())
                .read(Boolean.TRUE.equals(source.getRead()))
                .createdAt(source.getCreatedAt())
                .readAt(source.getReadAt())
                .build();
    }

    private String trimToLength(String value, int maxLength, String fallback) {
        if (value == null || value.trim().isEmpty()) return fallback;
        String normalized = value.trim();
        if (normalized.length() <= maxLength) return normalized;
        return normalized.substring(0, maxLength);
    }
}
