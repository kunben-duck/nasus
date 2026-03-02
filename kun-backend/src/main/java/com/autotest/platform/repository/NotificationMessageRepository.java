package com.autotest.platform.repository;

import com.autotest.platform.entity.NotificationMessage;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@Repository
public interface NotificationMessageRepository extends JpaRepository<NotificationMessage, Long> {

    Page<NotificationMessage> findByUserIdAndTenantIdOrderByCreatedAtDesc(Long userId, Long tenantId, Pageable pageable);

    Page<NotificationMessage> findByUserIdAndTenantIdAndReadFalseOrderByCreatedAtDesc(Long userId, Long tenantId, Pageable pageable);

    Optional<NotificationMessage> findByIdAndUserIdAndTenantId(Long id, Long userId, Long tenantId);

    long countByUserIdAndTenantIdAndReadFalse(Long userId, Long tenantId);

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("""
            UPDATE NotificationMessage n
               SET n.read = true,
                   n.readAt = :readAt
             WHERE n.userId = :userId
               AND n.tenantId = :tenantId
               AND n.read = false
            """)
    int markAllAsRead(@Param("userId") Long userId,
                      @Param("tenantId") Long tenantId,
                      @Param("readAt") LocalDateTime readAt);

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("""
            DELETE FROM NotificationMessage n
             WHERE n.userId = :userId
               AND n.tenantId = :tenantId
               AND n.id IN :ids
            """)
    int deleteByUserIdAndTenantIdAndIds(@Param("userId") Long userId,
                                        @Param("tenantId") Long tenantId,
                                        @Param("ids") List<Long> ids);
}
