package com.autotest.platform.repository;

import com.autotest.platform.entity.TenantMembership;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface TenantMembershipRepository extends JpaRepository<TenantMembership, Long> {

    @Query("SELECT tm FROM TenantMembership tm WHERE tm.user.id = :userId AND tm.status = :status ORDER BY tm.tenant.tenantName ASC")
    List<TenantMembership> findByUserIdAndStatus(@Param("userId") Long userId,
                                                 @Param("status") TenantMembership.MembershipStatus status);

    @Query("SELECT tm FROM TenantMembership tm WHERE tm.tenant.id = :tenantId AND tm.status = :status ORDER BY tm.createdAt ASC")
    List<TenantMembership> findByTenantIdAndStatus(@Param("tenantId") Long tenantId,
                                                   @Param("status") TenantMembership.MembershipStatus status);

    Optional<TenantMembership> findByTenantIdAndUserId(Long tenantId, Long userId);

    @Query("SELECT tm FROM TenantMembership tm WHERE tm.user.id = :userId AND tm.tenant.id = :tenantId AND tm.status = :status")
    Optional<TenantMembership> findByUserIdAndTenantIdAndStatus(@Param("userId") Long userId,
                                                                 @Param("tenantId") Long tenantId,
                                                                 @Param("status") TenantMembership.MembershipStatus status);

    boolean existsByTenantIdAndUserIdAndStatus(Long tenantId,
                                               Long userId,
                                               TenantMembership.MembershipStatus status);
}
