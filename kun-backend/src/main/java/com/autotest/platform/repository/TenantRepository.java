package com.autotest.platform.repository;

import com.autotest.platform.entity.Tenant;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface TenantRepository extends JpaRepository<Tenant, Long> {

    Optional<Tenant> findByTenantCode(String tenantCode);

    boolean existsByTenantCode(String tenantCode);

    List<Tenant> findByOwnerAdminIdOrderByCreatedAtDesc(Long ownerAdminId);

    Optional<Tenant> findByIdAndOwnerAdminId(Long id, Long ownerAdminId);
}
